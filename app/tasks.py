import json
import sys
import time

from flask import render_template
from rq import get_current_job

from app import create_app, db
from app.email import send_email
from app.models import User, Post, Task, Message

app = create_app()
app.app_context().push()


def _set_task_progress(progress):
    job = get_current_job()
    if job:
        job.meta['progress'] = progress
        job.save_meta()
        task = Task.query.get(job.get_id())
        task.user.add_notification('task_progress', {'task_id': job.get_id(),
                                                     'progress': progress})
        if progress >= 100:
            task.complete = True
        db.session.commit()

def suggest_edits(user_id):
    try:
        posts = Post.query.filter(Post.author == user_id).all()
        _set_task_progress(0)
        
        for post in posts:
            if not post.does_preview_exist():
                Message.send_sys_message(user_id)

        _set_task_progress(100)
    except: 
        _set_task_progress(0)
        app.logger.error('Unhandled exception', exc_info=sys.exc_info())
        
def export_posts(user_id):
    try:
        user = User.query.get(user_id)
        _set_task_progress(0)
        data = []
        i = 0
        total_posts = user.posts.count()
        for post in user.posts.order_by(Post.timestamp.asc()):
            data.append({'body': post.body,
                         'timestamp': post.timestamp.isoformat() + 'Z'})
            time.sleep(5)
            i += 1
            _set_task_progress(100 * i // total_posts)

        send_email('[Microblog] Your blog posts',
                   sender=app.config['ADMINS'][0], recipients=[user.email],
                   text_body=render_template('email/export_posts.txt', user=user),
                   html_body=render_template('email/export_posts.html',
                                             user=user),
                   attachments=[('posts.json', 'application/json',
                                 json.dumps({'posts': data}, indent=4))],
                   sync=True)
    except:
        _set_task_progress(100)
        app.logger.error('Unhandled exception', exc_info=sys.exc_info())
