from datetime import datetime
from flask import render_template, flash, redirect, url_for, request, g, \
    jsonify, current_app, send_file, abort
from flask_login import current_user, login_required
from flask_babel import _, get_locale
from guess_language import guess_language
from app import db, current_app
from app.main.forms import EditProfileForm, PostForm, SearchForm, MessageForm, CommentForm, PostEditForm
from app.models import User, Post, Message, Notification, Misc, Comment, Changelog
from app.translate import translate
from app.main import bp

from markdown import markdown
import markdown.extensions.fenced_code

import functools
import os
from os import urandom
import binascii

import nude

from datetime import datetime, timedelta

def has_role(name):
    def real_decorator(f):
        def wraps(*args, **kwargs):
            if current_user.has_role(name):
                return f(*args, **kwargs)
            else:
                abort(403)
        return functools.update_wrapper(wraps, f)
    return real_decorator

@bp.before_app_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        current_user.last_ip = request.remote_addr
        db.session.commit()
        g.search_form = SearchForm()
    g.locale = str(get_locale())

 
@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = None
    time_passed = None

    latest_post = Post.query.filter(Post.user_id == current_user.id).order_by(Post.timestamp.desc()).first()

    if latest_post:
        time_passed = latest_post.timestamp - datetime.utcnow()

    if time_passed is None or Post.has_post_timer_expired(time_passed):
        form = PostForm()
        if form.validate_on_submit():

            language = guess_language(form.post.data)
            if language == 'UNKNOWN' or len(language) > 5:
                language = ''

            title = form.title.data
            modArchive = form.modFile.data
            modPreview = form.previewFile.data
            branch = form.branchField.data
            data = None
            mod_preview = None

            if modArchive:
                data = Misc.save_and_get_mod(modArchive)

            if modPreview:
                mod_preview = Misc.save_and_get_picture(modPreview, 'modprev')

            print(data)
            post = Post(body=form.post.data, author=current_user,
                        title = title, mod_file = data, photo_mod = mod_preview, language=language,
                        branch = branch)

            db.session.add(post)
            db.session.commit()
            flash(_('Your post will be live any minute now! You can now edit your post directly from the Explore page. However, you must wait 20 minutes before another post could be made!'), 'thumbsup')

            return redirect(url_for('main.post_view'))

    page = request.args.get('page', 1, type=int)
    posts = current_user.followed_posts().paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.index', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('index.html', title=_('Home'), form=form,
                           posts=posts.items, next_url=prev_url,
                           prev_url=next_url)


@bp.route('/download/<filename>', methods=['GET', 'POST'])
@login_required
def download(filename):
    file_loc = os.path.join(current_app.root_path, 'static/moduploads', filename)
    if os.path.isfile(file_loc):
        post = Post.query.filter(Post.mod_file == filename).first_or_404()
        post.number_of_downloads += 1
        db.session.add(post)
        db.session.commit()
        return send_file(file_loc, as_attachment=True)
    else:
        return abort(404)

@bp.route('/admin/deletepost/<id>', methods=['POST', 'GET'])
@login_required
@has_role('admin')
def deletepost(id):
    Post.delete_post(id)
    flash(_('The post is now deleted!'), 'info')
    return redirect(url_for('main.explore'))

@bp.route('/admin/postverif/<id>', methods=['GET', 'POST'])
@login_required
@has_role('admin')
def verifpost(id):
    if Post.verif_post(id):
        flash(_('This post is now verified!'), 'info')
    else:
        flash(_('Post verification token has been removed!'), 'info')
    return redirect(url_for('main.post_view', postid=id))

@bp.route('/explore')
def explore():
    page = request.args.get('page', 1, type=int)
    posts = Post.query.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.explore', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.explore', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('explore.html', title=_('Explore'),
                           posts=posts.items, next_url=next_url,
                           prev_url=prev_url)

@bp.route('/user/<username>')
@login_required
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    posts = user.posts.order_by(Post.timestamp.desc()).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.user', username=user.username,
                       page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.user', username=user.username,
                       page=posts.prev_num) if posts.has_prev else None
    return render_template('user.html', user=user, posts=posts.items,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/user/<username>/popup')
@login_required
def user_popup(username):
    user = User.query.filter_by(username=username).first_or_404()
    return render_template('user_popup.html', user=user)

@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username)
    if form.validate_on_submit():
        if not current_user.has_role('premium') and form.username.data != current_user.username:
            flash("This function isn't available to the public just yet!", 'error')
            return render_template('edit_profile.html', title=_('Edit Profile'),
                           form=form)

        current_user.username = form.username.data
        current_user.about_me = form.about_me.data

        user_has_pic = False

        if form.profile_pic.data:
            #old
            if current_user.picture_id:
                old_picture_path = os.path.join(current_app.root_path, 'static/profile_pics', current_user.picture_id)
                if os.path.isfile(old_picture_path):
                    user_has_pic = True
            #for new
            picture_file = Misc.save_and_get_picture(form.profile_pic.data, 'profile_pics')
            picture_path = os.path.join(current_app.root_path, 'static/profile_pics', picture_file)
            if os.path.isfile(picture_path):
                if not nude.is_nude(picture_path):
                    current_user.picture_id = picture_file
                    flash(_('Your profile picture was changed'), 'info')
                    if user_has_pic is True:
                        os.remove(old_picture_path);
                else:
                    flash(_('Warnning: Malicious or possibly explicit image detected'), 'error')
                    os.remove(picture_path);
            else: flash(_('There was an error changing your picture, please contact us for info'), 'error')
        flash(_('Any changes were saved'), 'info')

        db.session.commit()
        return redirect(url_for('main.edit_profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit Profile'),
                           form=form)


@bp.route('/post/<postid>', methods=['GET', 'POST'])
@login_required
def post_view(postid):
    post_object = Post.query.filter(Post.id == postid).first_or_404()
    edit_form = PostEditForm()

    if edit_form.validate_on_submit():
        if post_object.author == current_user:

            body = edit_form.post.data
            title = edit_form.title.data
            modArchive = edit_form.modFile.data
            modPreview = edit_form.previewFile.data
            branch = edit_form.branchField.data

            if modArchive:
                data = Misc.save_and_get_mod(modArchive)
                post_object.mod_file = data
                print(data)

            if modPreview:
                mod_preview = Misc.save_and_get_picture(modPreview, 'modprev')
                post_object.photo_mod = mod_preview

            if body:
                post_object.body = body
            if title:
                post_object.title = title
            if branch:
                post_object.branch = branch

            db.session.add(post_object)
            db.session.commit()

            return redirect(url_for('main.post_view', postid=postid))

    form = CommentForm()
    if form.validate_on_submit() and form.submit_comment.data:
        if form.validate():
            new_comment = Comment()

            new_comment.author_id = current_user.id

            new_comment.body = form.body.data
            new_comment.post_id = postid

            new_comment.timestamp = datetime.utcnow()

            try:
                db.session.add(new_comment)
                db.session.commit()
            except Exception as e:
                flash('Error adding your comment: %s' % str(e), 'error')
                db.session.rollback()
            else:
                flash("Comment has been added.", 'info')
            return redirect(url_for('main.post_view', postid=postid))

    page = request.args.get('page', 1, type=int)
    comments = post_object.comments.order_by(Comment.timestamp.desc()).paginate(
        page, current_app.config['COMMENTS_PER_PAGE'], False)
    next_url = url_for('main.post_view', postid=postid, page=comments.next_num) \
        if comments.has_next else None
    prev_url = url_for('main.post_view', postid=postid,page=comments.prev_num) \
        if comments.has_prev else None

    return render_template('post.html', post=post_object, title=_('Mod ')+post_object.title,
    form=form, comments=comments.items, next_url=next_url, prev_url=prev_url, edit_form=edit_form)


@bp.route('/moderation/commentregulation/<int:id>')
@login_required
@has_role('admin')
def commentregulation(id):
    comment_id = Comment.moderate_comment(id)
    return redirect(url_for('main.post_view', postid=comment_id))

@bp.route('/follow/<username>')
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(_('User %(username)s not found.', username=username), 'error')
        return redirect(url_for('main.index'))
    if user == current_user:
        flash(_('You cannot follow yourself!'), 'error')
        return redirect(url_for('main.user', username=username))
    current_user.follow(user)
    db.session.commit()
    flash(_('You are following %(username)s!', username=username), 'info')
    return redirect(url_for('main.user', username=username))


@bp.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash(_('User %(username)s not found.', username=username), 'error')
        return redirect(url_for('main.index'))
    if user == current_user:
        flash(_('You cannot unfollow yourself!'), 'error')
        return redirect(url_for('main.user', username=username))
    current_user.unfollow(user)
    db.session.commit()
    flash(_('You are not following %(username)s.', username=username), 'info')
    return redirect(url_for('main.user', username=username))


@bp.route('/translate', methods=['POST'])
@login_required
def translate_text():
    return jsonify({'text': translate(request.form['text'],
                                      request.form['source_language'],
                                      request.form['dest_language'])})


@bp.route('/search')
@login_required
def search():
    if not g.search_form.validate():
        return redirect(url_for('main.explore'))
    page = request.args.get('page', 1, type=int)
    posts, total = Post.search(g.search_form.q.data, page,
                               current_app.config['POSTS_PER_PAGE'])
    next_url = url_for('main.search', q=g.search_form.q.data, page=page + 1) \
        if total > page * current_app.config['POSTS_PER_PAGE'] else None
    prev_url = url_for('main.search', q=g.search_form.q.data, page=page - 1) \
        if page > 1 else None
    return render_template('search.html', title=_('Search'), posts=posts,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/send_message/<recipient>', methods=['GET', 'POST'])
@login_required
def send_message(recipient):
    user = User.query.filter_by(username=recipient).first_or_404()
    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(author=current_user, recipient=user,
                      body=form.message.data)
        db.session.add(msg)
        user.add_notification('unread_message_count', user.new_messages())
        db.session.commit()
        flash(_('Your message has been sent.'), 'info')
        return redirect(url_for('main.user', username=recipient))
    return render_template('send_message.html', title=_('Send Message'),
                           form=form, recipient=recipient)


@bp.route('/messages')
@login_required
def messages():
    current_user.last_message_read_time = datetime.utcnow()
    current_user.add_notification('unread_message_count', 0)
    db.session.commit()
    page = request.args.get('page', 1, type=int)
    messages = current_user.messages_received.order_by(
        Message.timestamp.desc()).paginate(
            page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = url_for('main.messages', page=messages.next_num) \
        if messages.has_next else None
    prev_url = url_for('main.messages', page=messages.prev_num) \
        if messages.has_prev else None
    return render_template('messages.html', messages=messages.items,
                           next_url=next_url, prev_url=prev_url, title=_('Inbox'))


@bp.route('/export_posts')
@login_required
def export_posts():
    if current_user.get_task_in_progress('export_posts'):
        flash(_('An export task is currently in progress'), 'error')
    else:
        current_user.launch_task('export_posts', _('Exporting posts...'))
        db.session.commit()
    return redirect(url_for('main.user', username=current_user.username))


@bp.route('/notifications')
@login_required
def notifications():
    since = request.args.get('since', 0.0, type=float)
    notifications = current_user.notifications.filter(
        Notification.timestamp > since).order_by(Notification.timestamp.asc())
    return jsonify([{
        'name': n.name,
        'data': n.get_data(),
        'timestamp': n.timestamp
    } for n in notifications])

@bp.route('/learningcenter')
@login_required
def learningcenter():
    return render_template('learningcenter/main.html', title="Learning Center")

@bp.route('/policy')
def policy():
    return render_template('policy.html', title="Guideline")

@bp.route('/changelog')
def changelog():
    md_template_string = markdown.markdown(
        Changelog.get_changelog(), extensions=["fenced_code"]
    )
    return render_template('revision/revision.html', title="Devlog", items=md_template_string)
