from app import create_app, db, cli, current_app
from app.models import User, Post, Message, Notification, Task

from flask_mobility import Mobility
import os

app = create_app()
cli.register(app)

Mobility(app)

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Post': Post, 'Message': Message,
            'Notification': Notification, 'Task': Task}

def is_valid_download(filename):
    file_loc = os.path.join(current_app.root_path, 'static/moduploads', filename)
    if os.path.isfile(file_loc):
        return True
    else: return False
app.jinja_env.globals.update(is_valid_download=is_valid_download)
