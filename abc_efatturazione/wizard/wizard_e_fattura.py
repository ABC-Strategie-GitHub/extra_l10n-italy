import logging
import datetime
import requests
import json
import base64


from odoo import models, fields, api, _
from odoo.exceptions import Warning


_logger = logging.getLogger('Sending E-Invoice')

class WizardEFattura(models.TransientModel):

    _name = "wizard.efattura"
    _description = "Wizard For Sending E-Invoice"
    
    def _check_invoices_before_sending(self, invoices):
        errors = []
        for invoice in invoices:
            if not invoice.partner_id.electronic_invoice_subjected:
                errors.append((
                    invoice.partner_id.name,
                    _('Partner is not electronic invoice subjected')))
                 
            if not invoice.journal_id.e_fattura:
                errors.append((invoice.name, _('Selected journal is '
                                               'incorrect.'
                                               '\nIs not E-invoice')))
            elif invoice.state in ('draft', 'cancel'):
                errors.append((invoice.name, _('is not validate')))
            elif invoice.e_state in ('sent', 'done'):
                errors.append((invoice.name, _('has already been processed')))
            elif not invoice.fatturapa_attachment_out_id:
                errors.append((invoice.name, _('XML is not ready')))
                
            id_to_check = invoice.fatturapa_attachment_out_id.id
            for i in invoices:
                if i.id != invoice.id and i.fatturapa_attachment_out_id.id == id_to_check:
                    errors.append((invoice.name, _('XML of the invoice '+invoice.name+' of invoice '+i.name+', select only one of the two invoices.')))
        if errors:
            text = u'The following invoices have errors:\n'
            for error in errors:
                text = text + u'{n} - {e}\n'.format(n=error[0], e=error[1])
            raise Warning(_(text))
    
    def call_send_invoice(self):
        invoice_ids = self.env.context.get('active_ids', [])
        
        if not invoice_ids:
            raise Warning('No invoices to send')
            
        invoice_model = self.env['account.move']
        invoices = invoice_model.browse(invoice_ids)
        self._check_invoices_before_sending(invoices)
        company = self.env.user.company_id
        for invoice in invoices:
            # ----- Try to generate documents (PDF or XML) to send
            try:
                invoice.sendEfatturaAdE()
                
            except Exception as invoice_error:
                error_text = _('Error in invoice %s:\n\n%s') % (
                    invoice.name, invoice_error)
                raise Warning(error_text)
        
        return {'type': 'ir.actions.act_window_close'}