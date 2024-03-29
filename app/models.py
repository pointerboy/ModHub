import base64
import json
import os
from datetime import datetime, timedelta
from hashlib import md5
from time import time

import jwt
import redis
import rq
from flask import current_app, url_for, send_from_directory
from flask_login import UserMixin
from flask_uploads import UploadSet, configure_uploads, IMAGES, patch_request_class
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug import secure_filename

from app import db, login
from app.search import add_to_index, remove_from_index, query_index

from zipfile import ZipFile

import os
from os import urandom
import binascii
import bleach

from markdown import markdown

class SearchableMixin(object):
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return cls.query.filter_by(id=0), 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        return cls.query.filter(cls.id.in_(ids)).order_by(
            db.case(when, value=cls.id)), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in cls.query:
            add_to_index(cls.__tablename__, obj)


db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)

class PaginatedAPIMixin(object):
    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        resources = query.paginate(page, per_page, False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page,
                                **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page,
                                **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page,
                                **kwargs) if resources.has_prev else None
            }
        }
        return data


followers = db.Table(
    'followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

class User(UserMixin, PaginatedAPIMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    about_me = db.Column(db.String(140))
    picture_id = db.Column(db.String(120))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(32), index=True, unique=True)
    token_expiration = db.Column(db.DateTime)

    ip = db.Column(db.String(16))
    last_ip = db.Column(db.String(16))

    vk_username = db.Column(db.String(18))
    
    roles = db.Table(
        'role_users',
        db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
        db.Column('role_id', db.Integer, db.ForeignKey('role.id'))
    )

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    messages_sent = db.relationship('Message',
                                    foreign_keys='Message.sender_id',
                                    backref='author', lazy='dynamic')
    messages_received = db.relationship('Message',
                                        foreign_keys='Message.recipient_id',
                                        backref='recipient', lazy='dynamic')
    last_message_read_time = db.Column(db.DateTime)
    notifications = db.relationship('Notification', backref='user',
                                    lazy='dynamic')
    tasks = db.relationship('Task', backref='user', lazy='dynamic')

    roles = db.relationship(
        'Role',
        secondary=roles,
        backref=db.backref('users', lazy='dynamic')
    )

    comments = db.relationship(
        'Comment',
        backref='author',
        lazy='dynamic'
        )

    user_theme = db.Column(db.String(6), default="default_theme")

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        return url_for('static', filename='profile_pics/' + str(self.picture_id)) 
        
        #digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        #return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
          #  digest, size)

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

        return False
    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0

    def is_online(self):
        """A user is online if they were last seen less than 2 minutes ago."""
        return (datetime.utcnow() - self.last_seen).total_seconds() < 2 * 60

    def followed_posts(self):
        followed = Post.query.join(
            followers, (followers.c.followed_id == Post.user_id)).filter(
            followers.c.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.timestamp.desc())

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'],
            algorithm='HS256').decode('utf-8')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)

    def new_messages(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        return Message.query.filter_by(recipient=self).filter(
            Message.timestamp > last_read_time).count()

    def add_notification(self, name, data):
        self.notifications.filter_by(name=name).delete()
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def launch_task(self, name, description, *args, **kwargs):
        rq_job = current_app.task_queue.enqueue('app.tasks.' + name, self.id,
                                                *args, **kwargs)
        task = Task(id=rq_job.get_id(), name=name, description=description,
                    user=self)
        db.session.add(task)
        return task

    def get_tasks_in_progress(self):
        return Task.query.filter_by(user=self, complete=False).all()

    def get_task_in_progress(self, name):
        return Task.query.filter_by(name=name, user=self,
                                    complete=False).first()

    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'username': self.username,
            'last_seen': self.last_seen.isoformat() + 'Z',
            'about_me': self.about_me,
            'post_count': self.posts.count(),
            'follower_count': self.followers.count(),
            'followed_count': self.followed.count(),
            '_links': {
                'self': url_for('api.get_user', id=self.id),
                'followers': url_for('api.get_followers', id=self.id),
                'followed': url_for('api.get_followed', id=self.id),
                'avatar': self.avatar(128)
            }
        }
        if include_email:
            data['email'] = self.email
        return data

    def from_dict(self, data, new_user=False):
        for field in ['username', 'email', 'about_me']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    def get_token(self, expires_in=3600):
        now = datetime.utcnow()
        if self.token and self.token_expiration > now + timedelta(seconds=60):
            return self.token
        self.token = base64.b64encode(os.urandom(24)).decode('utf-8')
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    def revoke_token(self):
        self.token_expiration = datetime.utcnow() - timedelta(seconds=1)

    @staticmethod
    def check_token(token):
        user = User.query.filter_by(token=token).first()
        if user is None or user.token_expiration < datetime.utcnow():
            return None
        return user

    def has_role(self, name):
        for role in self.roles:
            if role.name == name:
                return True
        return False


@login.user_loader
def load_user(id):
    return User.query.get(int(id))

class Role(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<Role {}'.format(self.name)

class Comment(SearchableMixin, db.Model):
    __searchable__ = ['body']
    
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text)

    body_html = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.now)
    disabled = db.Column(db.Boolean)

    post_id = db.Column(db.Integer, db.ForeignKey('post.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    @staticmethod
    def moderate_comment(comment_id):
        comment = Comment.query.get_or_404(comment_id)
        comment.disabled = not comment.disabled
        db.session.add(comment)
        db.session.commit()

        return comment.post_id

    @staticmethod
    def on_changed_body(target, value, oldvalue, initiator):
        allowed_tags = ['a', 'abbr', 'acronym', 'b', 'code', 'em', 'i',
        'strong']
        target.body_html = bleach.linkify(bleach.clean(
        markdown(value, output_format='html'),
        tags=allowed_tags, strip=True))

db.event.listen(Comment.body, 'set', Comment.on_changed_body)
class Post(SearchableMixin, db.Model):
    __searchable__ = ['body']
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(64))
    body = db.Column(db.Text)
    body_html = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    language = db.Column(db.String(5))

    mod_file = db.Column(db.String(23+1))
    photo_mod = db.Column(db.String(23+1))

    verified = db.Column(db.Integer)
    disabled = db.Column(db.Integer)

    branch = db.Column(db.String(8))
    number_of_downloads = db.Column(db.Integer, default=0)

    def list_contents(self):
        contents = []
        if self.mod_file:
            print(self.mod_file)
            try:
                file_loc = os.path.join(current_app.root_path, 'static/moduploads', self.mod_file)
                with ZipFile(file_loc, 'r') as obj:
                    listOfFiles = obj.namelist()
                    for element in listOfFiles:
                        print(element)
                        contents.append(element)
            except:
                contents.append("The list of files cannot be processed. You can still download the file.")
            return contents
        return None

    def does_preview_exist(self):
        if os.path.isfile(os.path.join(current_app.root_path,  'static/modprev', str(self.photo_mod))):
            return True
        return False

    def get_preview(self):
        filename = str(self.photo_mod)
        path_to_thumb = url_for('static', filename='modprev/' + filename)

        if not self.does_preview_exist():
            filename = "no_preview.png"
            path_to_thumb = url_for('static', filename='modprev/' + filename)
        
        return path_to_thumb

    @staticmethod
    def delete_post(id):
        deleteObj = Post.query.filter(Post.id == id).first()
        db.session.delete(deleteObj)
        db.session.commit()
    
    @staticmethod
    def verif_post(id):
        postObj = Post.query.filter(Post.id == id).first()
        postObj.verified = not postObj.verified
        db.session.add(postObj)
        db.session.commit()
        return postObj.verified

    @staticmethod
    def has_post_timer_expired(timestamp):
        result = divmod(timestamp.days * 24 * 60 * 60 + timestamp.seconds, 60)
        
        if result[0] < - current_app.config["POST_COOLDOWN_MIN"]:
            return True

        return False

    comments = db.relationship(
            'Comment',
            backref='post',
            lazy='dynamic'
    )

    @staticmethod
    def on_changed_body(target, value, oldvalue, initiator):
        allowed_tags = ['a', 'addr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i',
                            'em','li', 'ol', 'pre', 'strong', 'ul', 'h1', 'h2', 'h3', 'p']
        
        target.body_html = bleach.linkify(bleach.clean(markdown(value, output_format='html'),
                                tags = allowed_tags, strip=True))

    # Utils
    @staticmethod
    def can_pass_upload_limit(upl_file_size):
        size = Misc.bytesto(upl_file_size, 'm')

        if size > 150:
            return False
        return True
        
    def __repr__(self):
        return '<Post {}>'.format(self.body)

db.event.listen(Post.body, 'set', Post.on_changed_body)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    @staticmethod
    def send_sys_message(recipient):
        user = User.query.filter_by(username=recipient).first_or_404()

        message = Message(author='system', recipient=user, body='Nice.')
        db.session.add(message)
        user.add_notification('unread_message_count', user.new_messages())
        db.session.commit()

    def __repr__(self):
        return '<Message {}>'.format(self.body)
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.Float, index=True, default=time)
    payload_json = db.Column(db.Text)

    def get_data(self):
        return json.loads(str(self.payload_json))


class Task(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(128), index=True)
    description = db.Column(db.String(128))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    complete = db.Column(db.Boolean, default=False)

    def get_rq_job(self):
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=current_app.redis)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100

class Misc():
    @staticmethod
    def save_and_get_picture(picture_data, location):
        secure_hex =  binascii.hexlify(os.urandom(8))
        secure_filename(picture_data.filename)

        _, f_ext = os.path.splitext(picture_data.filename)
        picture_file = str(secure_hex) + f_ext

        picture_data.save(os.path.join(current_app.root_path, 'static/'+location, picture_file))
        return picture_file

    @staticmethod
    def save_and_get_mod(mod_data, post_title):
        secure_hex =  binascii.hexlify(os.urandom(1))
        secure_filename(mod_data.filename)

        _, f_ext = os.path.splitext(mod_data.filename)
        mod_file = "modhub_" + post_title + str(secure_hex) + f_ext

        mod_data.save(os.path.join(current_app.root_path, 'static/moduploads', mod_file))
        return mod_file
    
    @staticmethod
    def bytesto(bytes, to, bsize=1024):
        a = {'k' : 1, 'm': 2, 'g' : 3, 't' : 4, 'p' : 5, 'e' : 6 }
        r = float(bytes)
        for i in range(a[to]):
            r = r / bsize

        return(r)

class Changelog():
    @staticmethod
    def get_changelog():
        file = open(os.path.join(current_app.root_path, 'static', 'CHANGELOG.md'), "r")
        return file.read()