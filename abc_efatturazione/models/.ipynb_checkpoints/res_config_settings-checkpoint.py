# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    password_efattura = fields.Char(string="Password", help ="Password E-Invoice")
    
    apiKey_efattura = fields.Char(string="Username", help ="Username E-Invoice")
    
    urlLogin = fields.Char(string="Url login", help ="Url to login")
    urlBase = fields.Char(string="Url base", help ="Base URL to make other calls")
        
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        res.update(
            password_efattura = self.env['ir.config_parameter'].sudo().get_param('abc_efatturazione.password_efattura'),
            apiKey_efattura = self.env['ir.config_parameter'].sudo().get_param('abc_efatturazione.apiKey_efattura'),
            urlLogin = self.env['ir.config_parameter'].sudo().get_param('abc_efatturazione.urlLogin'),
            urlBase = self.env['ir.config_parameter'].sudo().get_param('abc_efatturazione.urlBase'),
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param('abc_efatturazione.password_efattura', self.password_efattura)
        self.env['ir.config_parameter'].sudo().set_param('abc_efatturazione.apiKey_efattura', self.apiKey_efattura)
        self.env['ir.config_parameter'].sudo().set_param('abc_efatturazione.urlLogin', self.urlLogin)
        self.env['ir.config_parameter'].sudo().set_param('abc_efatturazione.urlBase', self.urlBase)