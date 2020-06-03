from flask import request
from flask_babel import _, lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SubmitField, TextAreaField, SelectField, DecimalField
from wtforms.validators import ValidationError, DataRequired, Length

from app.models import User

class EditProfileForm(FlaskForm):
    username = StringField(_l('Username'), validators=[DataRequired()])
    about_me = TextAreaField(_l('About me'),
                             validators=[Length(max=60)])

    profile_pic = FileField(_l('New profile picture'), validators=[FileAllowed(['jpg', 'png'], 'Invalid file set for the profile picture. We support jpg and png.')])

    submit = SubmitField(_l('Submit'))
    def __init__(self, original_username, *args, **kwargs):
        super(EditProfileForm, self).__init__(*args, **kwargs)
        self.original_username = original_username

    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=self.username.data).first()
            if user is not None:
                raise ValidationError(_('Please use a different username.'))


class PostForm(FlaskForm):
    title = StringField(_l('Title of Modification'), validators=[DataRequired()])
    post = TextAreaField(_l('Description of the modification.'), validators=[DataRequired()])
    modFile = FileField(_('Mod File (.zip or .rar)'), validators=[FileRequired(),
    FileAllowed(['zip', 'rar'], 'Only zip and rar files allowed.')])
    previewFile = FileField(_('Thumbnail'), validators=[FileRequired(), FileAllowed(['jpg', 'png', 'gif'], 
        "Invalid file format. We only allow following image formats: jpg, png and gif.")])

    branchField = SelectField('Branch', choices=[
        ('Release', 'Release'),
        ('Beta Release', 'Beta'),
        ('Lost and Found', 'Lost and Found',)
    ], validators=[DataRequired()])
    submit = SubmitField(_l('Submit'))

class PostEditForm(FlaskForm):
    title = StringField(_l('Title of Modification'), validators=[Length(min=6,max=360)])
    post = TextAreaField(_l('Description of the modification.'), validators=[Length(min=6,max=360)])

    modFile = FileField(_('Reupload Modification file'), validators=[FileAllowed(['zip', 'rar'], 'Only zip and rar files allowed.')])
    previewFile = FileField(_('Thumbnail'), validators=[FileAllowed(['jpg', 'png', 'gif'], 
        "Invalid file format. We only allow following image formats: jpg, png and gif.")])
    
    submit = SubmitField(_('Edit'))

class SearchForm(FlaskForm):
    q = StringField(_l('Search'), validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        if 'formdata' not in kwargs:
            kwargs['formdata'] = request.args
        if 'csrf_enabled' not in kwargs:
            kwargs['csrf_enabled'] = False
        super(SearchForm, self).__init__(*args, **kwargs)


class MessageForm(FlaskForm):
    message = TextAreaField(_l('Message'), validators=[
        DataRequired(), Length(min=1, max=140)])
    submit = SubmitField(_l('Submit'))

class CommentForm(FlaskForm):
    body = TextAreaField('Comment', validators=[DataRequired(),
                                Length(min=4, max=140)])
    submit_comment = SubmitField('Submit')