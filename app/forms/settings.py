# app/forms/settings.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, BooleanField, DecimalField
from wtforms.validators import DataRequired, Optional, URL, NumberRange


class SettingsForm(FlaskForm):
    server_type   = SelectField(
        "Server Type",
        choices=[("plex", "Plex"), ("jellyfin", "Jellyfin"), ("emby", "Emby"), ("audiobookshelf", "Audiobookshelf")],
        validators=[DataRequired()],
    )
    server_name   = StringField("Server Name",   validators=[DataRequired()])
    server_logo_url = StringField("Server Logo URL", validators=[Optional(), URL()], description="URL to your server logo image")
    server_url    = StringField("Server URL",    validators=[DataRequired()])
    api_key       = StringField("API Key",       validators=[Optional()])
    libraries     = StringField("Libraries",     validators=[Optional()])
    allow_downloads_plex = BooleanField("Allow Downloads", default=False, validators=[Optional()])
    allow_tv_plex = BooleanField("Allow Live TV", default=False, validators=[Optional()])
    overseerr_url = StringField("Overseerr/Ombi URL", validators=[Optional(), URL()])
    ombi_api_key  = StringField("Ombi API Key",  validators=[Optional()])
    discord_id    = StringField("Discord ID",    validators=[Optional()])
    admin_email   = StringField("Admin Email",   validators=[Optional()], description="Contact email for users")
    external_url  = StringField("External URL", validators=[Optional()])
    

    def __init__(self, install_mode: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if install_mode:
            # During install wizard, libraries must be supplied
            self.libraries.validators = [DataRequired()]
            # api_key is mandatory for Plex/Jellyfin
            self.api_key.validators = [DataRequired()]


class PaymentSettingsForm(FlaskForm):
    kofi_account_url = StringField("Ko-fi Account URL", validators=[Optional(), URL()], description="Your Ko-fi profile URL (e.g., https://ko-fi.com/yourusername)")
    kofi_username = StringField("Ko-fi Username", validators=[Optional()], description="Your Ko-fi username (e.g., yourusername)")
    kofi_verification_token = StringField("Ko-fi Verification Token", validators=[Optional()])
    kofi_1_month_price = DecimalField("1 Month Price (USD)", validators=[Optional(), NumberRange(min=0.01)], places=2)
    kofi_3_month_price = DecimalField("3 Month Price (USD)", validators=[Optional(), NumberRange(min=0.01)], places=2)  
    kofi_6_month_price = DecimalField("6 Month Price (USD)", validators=[Optional(), NumberRange(min=0.01)], places=2)
    payment_model = SelectField(
        "Payment Model", 
        choices=[
            ("per_server", "Per Server (users pay for each server individually)"),
            ("all_servers", "All Servers (one payment covers access to all servers)")
        ],
        validators=[Optional()],
        description="Choose whether payments cover access to one server or all servers"
    )
