from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Optional, URL
 
class GeneralSettingsForm(FlaskForm):
    server_name = StringField("Display Name", validators=[DataRequired()])
    server_logo_url = StringField("Server Logo URL", validators=[Optional(), URL()], description="URL to your server logo image")
    admin_email = StringField("Admin Email", validators=[Optional()], description="Contact email for users")
    overseerr_url = StringField("Overseerr/Ombi URL", validators=[Optional(), URL()])
    ombi_api_key  = StringField("Ombi API Key", validators=[Optional()])
    discord_id   = StringField("Discord Server ID", validators=[Optional()]) 