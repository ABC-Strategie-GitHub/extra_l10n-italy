# -*- coding: utf-8 -*-
# Creato e commentato da AntRootLK
import logging
import datetime
import requests
import json
import base64


from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger('Sending E-Invoice')

class WizardEFattura(models.TransientModel):

    _name = "wizard.efattura"
    _description = "Wizard For Sending E-Invoice"

    def _check_invoices_before_sending(self, invoices):
        errors = []

        # Cicla le fatture, se errore lo ritorna
        for invoice in invoices:

            #Se il partner non ha soggetto obbligato flaggato
            if not invoice.partner_id.electronic_invoice_subjected:
                errors.append((
                    invoice.partner_id.name,
                    _('Partner is not electronic invoice subjected')))

            #Se il registro non ha e_fattura flaggato
            if not invoice.journal_id.e_fattura:
                errors.append((invoice.name, _('Selected journal is '
                                               'incorrect.'
                                               '\nIs not E-invoice')))
            #Se lo stato e' bozza o annullato
            elif invoice.state in ('draft', 'cancel'):
                errors.append((invoice.name, _('is not validate')))
            #Se lo stato e_fattura e' invato, invio in corso o accettata
            elif invoice.e_state in ('sent', 'accepted', 'sending'):
                errors.append((invoice.name, _('has already been processed')))

            id_to_check = invoice.fatturapa_attachment_out_id.id

            #DEL per incompatibilta con il resto della funzione
            #for i in invoices:
            #    if i.id != invoice.id and i.fatturapa_attachment_out_id.id == id_to_check:
            #        errors.append((invoice.name, _('XML of the invoice '+invoice.name+' of invoice '+i.name+', select only one of the two invoices.')))
        if errors:

            for error in errors:
                text =  u'{n} - {e}\n'.format(n=error[0], e=error[1])
            return (_(text))

    def call_send_invoice(self):
        invoice_ids = self.env.context.get('active_ids', [])

        if not invoice_ids:
            raise UserError('No invoices to send')

        invoice_model = self.env['account.move']
        invoices = invoice_model.browse(invoice_ids)

        company = self.env.user.company_id
        error = ""
        for invoice in invoices:

            #Se ho errore lo concateno a error
            if(self._check_invoices_before_sending(invoice)):
                error += self._check_invoices_before_sending(invoice)
            else:
                # ----- Try to generate documents (PDF or XML) to send
                try:
                    #Se non c'e' xml procede a crearlo e quindi invia il file altrimenti segnala che e' gia' presente un xml
                    wiz_exp = self.env['wizard.export.fatturapa'].create({})
                    if wiz_exp._fields.get('include_ddt_data', False):
                        wiz_exp.include_ddt_data = 'dati_ddt'
                    wiz_exp.with_context(
                        active_ids=[invoice.id, ]).exportFatturaPA()
                    if not invoice.fatturapa_attachment_out_id:
                        error += (_('XML is not ready in invoice %s\n') % (invoice.name))

                    #Chiamo la send
                    invoice.sendEfatturaAdE()
                    #Committo per avere sempre i valori aggiornati
                    self.env.cr.commit()


                except Exception as invoice_error:
                    error += _('Error in invoice %s:\n%s\n\n') % (
                        invoice.name, invoice_error)

        #Se c'e' errore lo stampo, non si chiudera' il wizard ovviamente, TO FIX?
        if(len(error)>0):
            text = u'The following invoices have errors:\n' + _(error)
            raise UserError(_(text))

        return {'type': 'ir.actions.act_window_close'}
