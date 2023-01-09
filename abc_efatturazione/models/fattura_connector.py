# -*- coding: utf-8 -*-
# Creato e commentato da AntRootLK
from odoo import models, fields, api, _
import requests
import ssl
from urllib3 import poolmanager
import json
import logging
from odoo.exceptions import UserError, Warning
from datetime import datetime, timedelta
import time, base64, zipfile, io
from bs4 import BeautifulSoup

_logger = logging.getLogger(__name__)

_e_states = [
        ('draft', 'Draft'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('accepted', 'Accepted'),
        ('rejected','Rejected'),
        ('not_delivered', 'Not Delivered'),
        ('error', 'Error'),]
    
    
    
class TLSAdapter(requests.adapters.HTTPAdapter):
    

    def init_poolmanager(self, connections, maxsize, block=False):
        """Create and initialize the urllib3 PoolManager."""
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        self.poolmanager = poolmanager.PoolManager(
                num_pools=connections,
                maxsize=maxsize,
                block=block,
                ssl_version=ssl.PROTOCOL_TLS,
                ssl_context=ctx)
        
        
        
class AccountMove(models.Model):
    _inherit = "account.move"
    
    e_state = fields.Selection(_e_states,
                               string='State E-Invoice',
                               default='draft', 
                               copy=False)
    
    history = fields.One2many('efattura.history', 
                              'name',
                              string='E-invoice history', 
                              copy=False)
    
    sdi_file_name = fields.Char('Sdi File Name', 
                                size=128, 
                                copy=False)
    
    #Funzione che converte il file xml per consentire l'invio al sistema di fatturazione
    def convertXML(self):
        
        for record in self:
            if(self.fatturapa_attachment_out_id):
                xml_to_send = self.fatturapa_attachment_out_id.datas
                xml_to_send = xml_to_send.decode("utf-8")                
                
                return xml_to_send
            else:
                raise UserError("Nessun XML trovato.")

    #Decodifica gli stati in arrivo dal sistema di fatturazione       
    def _decodeStatus(self, state):
        if(state == 'Presa in carico'):
            return "sending"

        elif(state == 'Inviata'):
            return "sent"

        elif(state == 'Consegnata'):
            return "delivered"

        elif(state == 'Accettata'):
            return "accepted"

        elif(state == 'Rifiutata'):
            return "rejected"
        
        elif(state == 'Non consegnata'):
            return "not_delivered"
        
        else:
            return "error"
    
    #Chiamata di login che permette di ottenere il token che verra' utilizzato nelle altre chiamate
    def _loginEfattura(self):
        if(self.sudo().env['res.config.settings'].get_values()['password_efattura'] and self.sudo().env['res.config.settings'].get_values()['apiKey_efattura']):
            password = self.sudo().env['res.config.settings'].get_values()['password_efattura']
            username = self.sudo().env['res.config.settings'].get_values()['apiKey_efattura']

        else:
            raise UserError("No data in config settings.")
        
        #Strutturo ed eseguo la chiamata
        url = self.sudo().env['res.config.settings'].get_values()['urlLogin']
        session = requests.session()
        session.mount('https://', TLSAdapter())
        #payload necessario per la chiamata, i dati non devono essere visibili nell'url
        payload = ('grant_type=password&username='+username+'&password='+password+'')

        res = session.post(url, data = payload, headers={'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'})
        if(res.status_code != 200):

            #Se c'e' un errore scrivo nel logger
            msg = res.status_code
            return -1, msg 

        else:
            #Ritorno il token e l'username
            return str(res.json()['access_token']), username
        
    #Funzione che consente l'invio della fattura al sistema di fatturazione 
    def sendEfatturaAdE(self):
        for record in self:
            
            session = requests.session()
            session.mount('https://', TLSAdapter())

            #Converto l'xml
            xml_to_send = record.convertXML()
            if(xml_to_send):
                name_fattura = record.fatturapa_attachment_out_id.name
            
            #Effettuo il login per ottenere un nuovo token
            token, username = self._loginEfattura()
            if(token == -1):
                _logger.info("Return status login - ERROR CODE {c}".format(
                    c=username))
                return
            vat = self.env.company.vat[2:]
            
            jsonPayload = { "dataFile": xml_to_send,
                            "credential": "",
                            "domain" : "",
                            "skipExtraSchema": "true"
                          }
            #Converto il payload
            payload = json.dumps(jsonPayload, ensure_ascii=False)
            
            #Strutturo ed eseguo la chiamata
            url = "{url}/services/invoice/upload".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase']) 
            res = session.post(url, data = payload, headers={'Authorization': 'Bearer '+token,'Content-Type': 'application/json;'})
            if(res.status_code != 200):

                #Se c'e' un errore scrivo nel logger
                _logger.info("Return status Invoice send - ERROR CODE {c}".format(
                    c=res.status_code))

            else:
                #Decodifico il ritorno della chiamata post
                resJson = res.json()

                #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
                if(resJson['errorCode'] != '0000'):

                    #Se l'errore non e' 0000 c'e' un errore di comunicazione, cambio stato e scrivo un messaggio nel chatter
                    error = "Something went wrong: ("+str(resJson['errorDescription'])+")! Contact support." 
                    record.e_state="error"
                    record.message_post(
                                         body = error, 
                                         message_type = "notification", 
                                         subject = "Sending error E-invoice", 
                                        )

                #Se non c'è un errore di comunicazione continuo il flusso
                else:

                    invoice = self.fatturapa_attachment_out_id.out_invoice_ids

                    #Se ci sono piu' fatture collegate alla efattura
                    if(len(invoice)>1):
                        for i in invoice:

                            #Aggiorno lo sdi_file_name con il valore tornato dal sistema di fatturazione e imposto lo stato su sending, scrivo quindi un messaggio nel chatter
                            i.sdi_file_name = resJson['uploadFileName']                    
                            i.e_state="sending"

                            i.message_post(
                                            body = "Sending E-Invoice on date "+str(datetime.now()), 
                                            message_type = "notification", 
                                            subject = "Status sending E-invoice", 
                                            #subtype_xmlid = "mail.mt_comment", 
                                            #partner_ids = partner_ids, 
                                            #notification_ids = notification_ids
                                           )

                    #Se c'e' una fattura collegata alla efattura
                    else:

                        #Aggiorno lo sdi_file_name con il valore tornato dal sistema di fatturazione e imposto lo stato su sending, scrivo quindi un messaggio nel chatter
                        record.sdi_file_name = resJson['uploadFileName']
                        record.e_state="sending"
                        record.message_post(
                                             body = "Sending E-Invoice on date "+str(datetime.now()),
                                             message_type = "notification", 
                                             subject = "Status sending E-invoice", 
                                             #subtype_xmlid = "mail.mt_comment", 
                                             #partner_ids = partner_ids, 
                                             #notification_ids = notification_ids
                                            )
                    
    #Funzione per cercare le fatture in uscita in base alla partita iva nel sistema di fatturazione [FIX PER CICLARE TUTTE LE FATTURE DELLE ULTIME 2 Settimane]
    def _searchEfattura(self, username, token, size, page):
        session = requests.session()
        session.mount('https://', TLSAdapter())
        ids= []
    
        #Strutturo ed eseguo la chiamata
        vat = self.env.company.vat[2:]
        time= (datetime.now() - timedelta(hours=336)).isoformat('#')
        #time2= (datetime.now() - timedelta(hours=40)).isoformat('#')
        
        param = "username={username}&countrySender=IT&vatcodeSender={vat}&size={size}&page={page}&startDate={time}".format(username = username.upper(), vat = vat, size=size, page=page ,time=time)
        url = "{url}/services/invoice/out/findByUsername?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param, time = time) 
        res = session.get(url, headers={'Authorization': 'Bearer '+str(token)})
        if(res.status_code != 200):

            #Se c'e' un errore scrivo nel logger
            return -1, res.status_code

        else:
            resJson = res.json()

            #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
            if(resJson['errorCode'] != '0000'):
                error = str(resJson['errorDescription'])

                #Ritorno -1 e la descrizione dell'errore
                return -1, error

            #Se non c'è un errore di comunicazione continuo il flusso
            else:       
                #Aggiungo a ids tutti i filename restituiti
                for content in resJson['content']:
                    ids.append(content['filename'])

                #Se non sono stati aggiunti filename a ids
                if(len(ids)==0):
                    error = "No invoice for this account"

                    #Ritorno -1 e la descrizione dell'errore
                    return -1, error

                #Ritorno la lista ids contenente i filename e "OK"
                return ids, "OK"
        
    #Funzione che consente l'aggiornamento massivo dello stato delle fatture dal sistema di fatturazione 
    def _getAllStatusAdE(self, size, page):

        session = requests.session()
        session.mount('https://', TLSAdapter())

        #Effettuo il login per ottenere un nuovo token
        token, username = self._loginEfattura()
        if(token == -1):
            _logger.info("Return status login - ERROR CODE {c}".format(
                    c=username))
            return
        vat = self.env.company.vat[2:]

        #Cerco le fatture nel sistema di fatturazione, mi verranno restituiti una lista di filename e lo status. Se lo status e' OK non c'e' errore.
        ids, status = self._searchEfattura(username, token, size, page)

        
        #Verifico che non ci sia errore nella chiamata di ricerca
        if(status == "OK"):

            
            for id in ids:
                
                #Sleep di 7 secondi perché il massimo di fatture che si possono richiedere in un minuto è 12
                time.sleep(7)
                #Verifico che esista almeno un record con sdi_file_name corrispondente 
                if(self.search([['sdi_file_name','=',id]])):
                    
                    #Strutturo ed eseguo la chiamata
                    param = "filename={file}".format(file=id)
                    url = "{url}/services/invoice/out/getByFilename?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 
                    
                    res = session.get(url, headers={'Authorization': 'Bearer '+token})
                    if(res.status_code != 200):
                        
                        #Se c'e' un errore scrivo nel logger
                        _logger.info("Return status Invoice get Status - ERROR CODE {c}".format(
                            c=res.status_code))
                    
                    else:
                        resJson = res.json()

                        #Cerco e ciclo tutti i record con sdi_file_name corrispondente al nome del file
                        records = self.search([['sdi_file_name', '=', id]])

                        for record in records:

                            #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
                            if(resJson['errorCode'] != '0000'):

                                #Aggiorno lo stato con il valore "error", creo un record contenente l'errore nella history della fattura
                                error = "Something went wrong: ("+str(resJson['errorDescription'])+")! Contact support." 
                                date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                record.e_state="error"

                                self.env['efattura.history'].create({'name': record.id, 
                                                                     'date': str(date), 
                                                                     'note': 'error', 
                                                                     'status_code': resJson['errorCode'], 
                                                                     'status_desc': resJson['errorDescription'], 
                                                                     'type':'error',
                                                                     })

                            #Se non c'è un errore di comunicazione continuo il flusso
                            else:

                                #Ottengo lo stato e la descrizione dello stato
                                state=resJson['invoices'][0]['status']
                                stateDesc=resJson['invoices'][0]['statusDescription']
                                date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                                #Decodifico lo stato e lo metto in una variabile, verifico che lo stato convertito non sia uguale allo stato del record. Se questi ultimi valori sono uguali non c'e' bisogno di
                                #creare un nuovo record di history
                                state_to_check = self._decodeStatus(state)
                                if(state_to_check != record.e_state):
                                    
                                    if(state_to_check=="error"):

                                        param = "filename={file}".format(file=id)
                                        url = "{url}/services/invoice/out/getZipByFilename?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 

                                        res = session.get(url, headers={'Authorization': 'Bearer '+token})
                                        if(res.status_code != 200):

                                            #Se c'e' un errore scrivo nel logger
                                            _logger.info("Return status Invoice get Status - ERROR CODE {c}".format(
                                                c=res.status_code))
                                            continue

                                        else:

                                            resJsonZip = zipfile.ZipFile(io.BytesIO(res.content), 'r')
                                            date_dummy = (datetime.now() - timedelta(days=365))
                                            for file in resJsonZip.namelist():

                                                if file[-3:]=="xml":
                                                    soup = BeautifulSoup(resJsonZip.read(file), 'xml')
                                                    dateRic = soup.find('DataOraRicezione').string[:-10]
                                                    dateRic = datetime.strptime(dateRic, '%Y-%m-%dT%H:%M:%S')

                                                    if(dateRic > date_dummy):
                                                        stateDesc = '[' + soup.find('Codice').string +'] '+ soup.find('Descrizione').string
                                                        date_dummy = dateRic
                                    
                                    #Creo un record di history con data, status_code e descrizione
                                    self.env['efattura.history'].create({'name': record.id, 
                                                                         'date': str(date), 
                                                                         'note': 'ok', 
                                                                         'status_code': state, 
                                                                         'status_desc': stateDesc, 
                                                                         'type':'positive'
                                                                         })
                                    #Aggiorno lo stato del record
                                    record.e_state = state_to_check
                        self.env.cr.commit()
                        _logger.info("Status Invoice committed - {f}".format(f=id))
        #C'e' un errore nella chiamata
        else:
            #Se c'e' un errore scrivo nel logger
            _logger.info("Status Invoice Update - ERROR INVOICE {c} - {f}".format(
                            c=ids, f=status))
      
    
    #Funzione che consente l'aggiornamento dello stato della fattura dal sistema di fatturazione       
    def getStatusEfatturaAdE(self):
        for record in self:
            
            session = requests.session()
            session.mount('https://', TLSAdapter())

            #Ottengo lo sdi_file_name dal record attuale
            xml_to_search = record.sdi_file_name

            #Effettuo il login per ottenere un nuovo token
            token, username = self._loginEfattura()
            if(token == -1):
                _logger.info("Return status login - ERROR CODE {c}".format(
                    c=username))
                return
            #Strutturo ed eseguo la chiamata
            param = "filename={file}".format(file = xml_to_search)
            url = "{url}/services/invoice/out/getByFilename?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 
            res = session.get(url, headers={'Authorization': 'Bearer '+token})
            if(res.status_code != 200):

                #Se c'e' un errore scrivo nel logger
                _logger.info("Return status Invoice - ERROR CODE {c}".format(
                    c=res.status_code))

            else:
                resJson = res.json()

                #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
                if(resJson['errorCode'] != '0000'):

                    #Aggiorno lo stato con il valore "error", creo un record contenente l'errore nella history della fattura
                    error = "Something went wrong: ("+str(resJson['errorDescription'])+")! Contact support." 
                    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    record.e_state="error"

                    self.env['efattura.history'].create({'name': record.id, 
                                                         'date': str(date), 
                                                         'note': 'error', 
                                                         'status_code': resJson['errorCode'], 
                                                         'status_desc': resJson['errorDescription'],
                                                         'type':'error',
                                                         })

                #Se non c'è un errore di comunicazione continuo il flusso
                else:

                    #Ottengo lo stato e la descrizione dello stato
                    state=resJson['invoices'][0]['status']
                    stateDesc=resJson['invoices'][0]['statusDescription']
                    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    #Decodifico lo stato e lo metto in una variabile, verifico che lo stato convertito non sia uguale allo stato del record. Se questi ultimi valori sono uguali non c'e' bisogno di
                    #creare un nuovo record di history
                    state_to_check = self._decodeStatus(state)
                    if(state_to_check != record.e_state):
                        
                        if(state_to_check=="error"):
                        
                            param = "filename={file}".format(file=xml_to_search)
                            url = "{url}/services/invoice/out/getZipByFilename?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 

                            res = session.get(url, headers={'Authorization': 'Bearer '+token})
                            if(res.status_code != 200):

                                #Se c'e' un errore scrivo nel logger
                                _logger.info("Return status Invoice get Status - ERROR CODE {c}".format(
                                    c=res.status_code))

                            else:

                                resJson = zipfile.ZipFile(io.BytesIO(res.content), 'r')
                                date_dummy = (datetime.now() - timedelta(days=365))
                                for file in resJson.namelist():

                                    if file[-3:]=="xml":
                                        soup = BeautifulSoup(resJson.read(file), 'xml')
                                        dateRic = soup.find('DataOraRicezione').string[:-10]
                                        dateRic = datetime.strptime(dateRic, '%Y-%m-%dT%H:%M:%S')

                                        if(dateRic > date_dummy):
                                            stateDesc = '[' + soup.find('Codice').string +'] '+ soup.find('Descrizione').string
                                            date_dummy = dateRic
                        
                        
                        
                        self.env['efattura.history'].create({'name': record.id, 
                                                             'date': str(date), 
                                                             'note': 'ok', 
                                                             'status_code': state, 
                                                             'status_desc': stateDesc, 
                                                             'type':'positive'
                                                             })
                        #Aggiorno lo stato del record
                        record.e_state = state_to_check

        
    #Funzione per la preview della fattura
    def view_preview_invoice_file(self):
        if self.e_state:
            url = self.fatturapa_attachment_out_id.ftpa_preview_link
            return {
                'name'     : 'preview XML',
                'res_model': 'ir.actions.act_url',
                'type'     : 'ir.actions.act_url',
                'target'   : 'current',
                'url'      : url,
            }
        
    #Funzione per la cron
    def cron_getAllStatusAdE(self, size, page):
        self._getAllStatusAdE(size, page)
            
class FatturaPAAttachmentOut(models.Model):
    
    _inherit = "fatturapa.attachment.out"
    
    e_state = fields.Selection(related='out_invoice_ids.e_state')
            
            
class FatturaPAAttachmentIn(models.Model):
    
    _inherit = "fatturapa.attachment.in"
    
    id_fatturazione_abc = fields.Char('ABC E-invoicing id', 
                                size=128, 
                                copy=False)
    
    
    #Chiamata di login che permette di ottenere il token che verra' utilizzato nelle altre chiamate
    def _loginEfattura(self):
            if(self.sudo().env['res.config.settings'].get_values()['password_efattura'] and self.sudo().env['res.config.settings'].get_values()['apiKey_efattura']):
                password = self.sudo().env['res.config.settings'].get_values()['password_efattura']
                username = self.sudo().env['res.config.settings'].get_values()['apiKey_efattura']
                
            else:
                raise UserError("No data in config settings.")

                
            #Strutturo ed eseguo la chiamata
            url = self.sudo().env['res.config.settings'].get_values()['urlLogin']
            session = requests.session()
            session.mount('https://', TLSAdapter())
            #payload necessario per la chiamata, i dati non devono essere visibili nell'url
            payload = ('grant_type=password&username='+username+'&password='+password+'')                        
            res = session.post(url, data = payload, headers={'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'})
            if(res.status_code != 200):

                #Se c'e' un errore scrivo nel logger
                return -1, res.status_code

            else:
                #Ritorno il token e l'username
                return str(res.json()['access_token']), username
    
    
    #Funzione per cercare le fatture in entrata in base alla partita iva nel sistema di fatturazione
    def _searchEfattura(self, username, token, size, page):
        session = requests.session()
        session.mount('https://', TLSAdapter())
        ids= []
    
        #Strutturo ed eseguo la chiamata
        vat = self.env.company.vat[2:]
        time= (datetime.now() - timedelta(days=30)).isoformat('#')
        #time2= (datetime.now() - timedelta(hours=40)).isoformat('#')
        param = "username={username}&countryReceiver=IT&vatcodeReceiver={vat}&size={size}&page={page}&startDate={time}".format(username = username.upper(), vat = vat, size=size, page=page ,time=time)
        url = "{url}/services/invoice/in/findByUsername?{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param) 
        res = session.get(url, headers={'Authorization': 'Bearer '+str(token)})
        if(res.status_code != 200):

            #Se c'e' un errore scrivo nel logger
            _logger.info("Return status search - ERROR CODE {c}".format(
                c=res.status_code))

        else:
            resJson = res.json()

            #Aggiungo a ids gli id restituiti
            for content in resJson['content']:
                ids.append(content['id'])

            #Se non sono stati aggiunti id a ids
            if(len(ids)==0):
                error = "No invoice for this account"

                #Ritorno -1 e la descrizione dell'errore
                return -1, error
            
            #Ritorno la lista ids contenente gli id e "OK"
            return ids, "OK"
    
    
    #Funzione che consente la ricezione massiva delle fatture dal sistema di fatturazione 
    def _receiveEfatturaAdE(self, size, page):
        session = requests.session()
        session.mount('https://', TLSAdapter())

        #Effettuo il login per ottenere un nuovo token
        token, username = self._loginEfattura()
        if(token == -1):
            _logger.info("Return status login - ERROR CODE {c}".format(
                        c=username))
            return
        vat = self.env.company.vat[2:]
        
        #Payload necessario per farci restituire il file xml
        jsonPayload = {"includePdf": "true",
                    "includeFile" : "true"
                   }
        payload = json.dumps(jsonPayload, ensure_ascii=False)

        #Cerco le fatture nel sistema di fatturazione, mi verranno restituiti una lista di id e lo status. Se lo status e' OK non c'e' errore.
        ids, status = self._searchEfattura(username, token, size, page)
        
        #Verifico che non ci sia errore nella chiamata di ricerca
        if(status == "OK"):
            
            for id in ids:
                
                #Sleep di 7 secondi perché il massimo di fatture che si possono richiedere in un minuto è 12
                time.sleep(7)
                
                #Strutturo ed eseguo la chiamata
                param = "{file}".format(file = id)
                url = "{url}/services/invoice/in/{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 
                res = session.get(url, data = payload, headers={'Authorization': 'Bearer '+token,'Content-Type': 'application/json;'})
                if(res.status_code != 200):

                    #Se c'e' un errore scrivo nel logger
                    _logger.info("Return receive invoice - ERROR CODE {c}".format(
                        c=res.status_code))

                else:
                    resJson = res.json()

                    #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
                    if(resJson['errorCode'] != '0000'):
                        error = str(resJson['errorDescription']) 

                        #Se c'e' un errore scrivo nel logger
                        _logger.info("Import Supplier Invoice - ERROR INVOICE {c} - {f}".format(
                                c=id, f=error))

                    #Se non c'è un errore di comunicazione continuo il flusso
                    else:

                        #Decodifico il file arrivato
                        file = str(base64.b64decode(resJson['file']))

                        #Filtro i file contenenti la stringa "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.0" dato che questa dava problemi di controllo nel modulo OCA
                        if("http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.0" in file):
                            continue

                        #Se non esistono record che hanno come id quello che stiamo ciclando
                        if(not self.search([['id_fatturazione_abc','=',id]]).id):
                            file = resJson['file']
                            filename = resJson['filename']

                            try:
                                #Creo un record di fattura_in con i dati ricevuti
                                einvoice_in = self.create({
                                                            'datas': file,
                                                            'att_name': filename,
                                                            'name': filename,
                                                            'company_id': self.env.company.id,
                                                            'id_fatturazione_abc': id,
                                                          })

                                self.env.cr.commit()
                                #Scrivo nel logger che l'operazione è andata a buon fine
                                _logger.info("Import Supplier Invoice - INVOICE {c} - {f}".format(
                                    c=id, f=resJson['filename']))

                            except UserError as error:

                                #Se c'e' un errore scrivo nel logger
                                _logger.info("Import Supplier Invoice - ERROR imported INVOICE {c} - {f} - {err}".format(
                                    c=id, f=vat, err=error))
                                pass
                            except Exception as error:

                                #Se c'e' un errore scrivo nel logger
                                _logger.info("Import Supplier Invoice - ERROR imported INVOICE {c} - {f}".format(
                                    c=id, f=vat))
                                continue
                            

        #C'e' un errore nella chiamata           
        else:
            
            #Se c'e' un errore scrivo nel logger
            _logger.info("Import Supplier Invoice - ERROR INVOICE {c} - {f}".format(
                            c=ids, f=status))

    #Funzione che consente la ricezione di una fattura dal sistema di fatturazione     
    def receiveSingleAdE(self, id):
        session = requests.session()
        session.mount('https://', TLSAdapter())

        #Effettuo il login per ottenere un nuovo token
        token, username = self._loginEfattura()
        if(token == -1):
            _logger.info("Return status login - ERROR CODE {c}".format(
                c=username))
            return
        vat = self.env.company.vat[2:]
        
        #Payload necessario per farci restituire il file xml
        jsonPayload = { "includePdf": "true",
                        "includeFile" : "true"
                       }
        payload = json.dumps(jsonPayload, ensure_ascii=False)

        #Strutturo ed eseguo la chiamata
        param = "{file}".format(file = id)
        url = "{url}/services/invoice/in/{param}".format( url= self.sudo().env['res.config.settings'].get_values()['urlBase'], param = param ) 
        res = session.get(url, data = payload, headers={'Authorization': 'Bearer '+token,'Content-Type': 'application/json;'})
        if(res.status_code != 200):

            #Se c'e' un errore scrivo nel logger
            _logger.info("Return status login - ERROR CODE {c}".format(
                c=res.status_code))

        else:
            resJson = res.json()

            #Verifico che l'errorCode tornato dalla chiamata sia diverso da 0000, altrimenti la chiamata va avanti
            if(resJson['errorCode'] != '0000'):
                error = str(resJson['errorDescription']) 

                #Se c'e' un errore scrivo nel logger
                _logger.info("Import Supplier Invoice - ERROR INVOICE {c} - {f}".format(
                        c=id, f=error))

            #Se non c'è un errore di comunicazione continuo il flusso
            else:

                #Se non esistono record che hanno come id quello che stiamo ciclando
                if(not self.search([['id_fatturazione_abc','=',id]]).id):
                    file = resJson['file']
                    filename = resJson['filename']
                    try:
                        #Creo un record di fattura_in con i dati ricevuti
                        einvoice_in = self.create({
                                                    'datas': file,
                                                    'att_name': filename,
                                                    'name': filename,
                                                    'company_id': self.env.company.id,
                                                    'id_fatturazione_abc': id,
                                                   })

                        #Scrivo nel logger che l'operazione è andata a buon fine
                        _logger.info("Import Supplier Invoice - INVOICE {c} - {f}".format(
                            c=id, f=resJson['filename']))

                    except UserError as error:

                        #Se c'e' un errore scrivo nel logger
                        _logger.info("Import Supplier Invoice - ERROR imported INVOICE {c} - {f} - {err}".format(
                            c=id, f=vat, err=error))
                        pass
                    except Exception as error:

                        #Se c'e' un errore scrivo nel logger
                        _logger.info("Import Supplier Invoice - ERROR imported INVOICE {c} - {f}".format(
                            c=id, f=vat))
                        pass
                    
        
    #Funzione per la cron
    def cron_receiveEfatturaAdE(self, size, page):
        self._receiveEfatturaAdE(size, page)
    
    
    
class EinvoiceHistory(models.Model):

    _name = "efattura.history"
    _description = "E-invoice history"
    _order = 'date'

    name = fields.Many2one('account.move', required=True,
                           ondelete='cascade')
    date = fields.Datetime(string='Date Action', required=True)
    note = fields.Text()
    status_code = fields.Char(size=25)
    status_desc = fields.Text()
    xml_content = fields.Text()
    
    type = fields.Selection([
        ('positive', 'OK'),
        ('error', 'ERROR')
    ])

    
class AccountJournal(models.Model):

    _inherit = "account.journal"

    e_fattura = fields.Boolean(
        string='Electronic Invoice',
        help="Check this box to determine that each entry of this journal\
            will be managed with Italian Electronical Invoice.", default=False)

    def get_journal_dashboard_datas(self):
        """
        Inherit for add in dashboard of account number of einvoice to sent
        and einvoice in error
        """
        res = super(AccountJournal, self).get_journal_dashboard_datas()
        number_efatture_error = number_efatture_draft = 0
        if self.type == 'sale':
            (query, query_args) = self._get_sent_error_ebills_query()
            self.env.cr.execute(query, query_args)
            query_efatture_error = self.env.cr.dictfetchall()

            (query, query_args) = self._get_draft_ebills_query()
            self.env.cr.execute(query, query_args)
            query_efatture_draft = self.env.cr.dictfetchall()

            curr_cache = {}
            (number_efatture_error) = self._count_results_efatture_error(query_efatture_error, curr_cache=curr_cache)
            (number_efatture_draft) = self._count_results_efatture_draft(query_efatture_draft, curr_cache=curr_cache)
 
            res.update({
                'number_efatture_error': number_efatture_error,
                'number_efatture_draft': number_efatture_draft,
                })
        return res

    def _get_sent_error_ebills_query(self):
        """
        Returns a tuple containing as its first element the SQL query used to
        gather the ebills in error state, and the arguments
        dictionary to use to run it as its second.
        """
        return ('''
            SELECT
                move.move_type,
                move.invoice_date,
                move.company_id
            FROM account_move move
            WHERE move.journal_id = %(journal_id)s
            AND move.e_state = 'error'
            AND move.move_type IN ('out_invoice', 'out_refund');
        ''', {'journal_id': self.id})

    def _count_results_efatture_error(self, results_dict, curr_cache=None):
        """ 
        Loops on a query result to count the total number of e-invoices
        in error state of sent
        """
        rslt_count = 0
        curr_cache = {} if curr_cache is None else curr_cache
        for result in results_dict:
            company = self.env['res.company'].browse(result.get('company_id')) or self.env.company
            rslt_count += 1
            date = result.get('invoice_date') or fields.Date.context_today(self)
        return (rslt_count)

    def _get_draft_ebills_query(self):
        """
        Returns a tuple containing as its first element the SQL query used to
        gather the e-bills in draft state, and the arguments
        dictionary to use to run it as its second.
        """
        return ('''
            SELECT
                move.move_type,
                move.invoice_date,
                move.company_id
            FROM account_move move
            WHERE move.journal_id = %(journal_id)s
            AND move.e_state = 'draft'
            AND move.state = 'posted'
            AND move.move_type IN ('out_invoice', 'out_refund');
        ''', {'journal_id': self.id})

    def _count_results_efatture_draft(self, results_dict, curr_cache=None):
        """ 
        Loops on a query result to count the total number of invoices
        confirmed to send which electronic invoice
        """
        rslt_count = 0
        curr_cache = {} if curr_cache is None else curr_cache
        for result in results_dict:
            company = self.env['res.company'].browse(result.get('company_id')) or self.env.company
            rslt_count += 1
            date = result.get('invoice_date') or fields.Date.context_today(self)
        return (rslt_count)
