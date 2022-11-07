# -*- coding: utf-8 -*-
{
    'name': "ABC - E-Fatturazione",

    'summary': """Modulo di integrazione con sistema di fatturazione""",

    'description': """Modulo di integrazione con sistema di fatturazione""",

    'author': "A.B.C. srl",
    'website': "https://www.abcstrategie.it",
    
    'category': 'Einvoice',
    'version': '14.0.0.6',
    
    'depends': ['base', 'account', 'l10n_it_fatturapa', 'l10n_it_fatturapa_out', 'l10n_it_fatturapa_in', 'sale', 'web', 'mail'],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings.xml',
        'wizard/wizard_e_fattura.xml',
        'views/account_move.xml',   
        'data/cron.xml',
    ],

    'sequence':1,
}
