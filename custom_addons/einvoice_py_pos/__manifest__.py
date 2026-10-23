{
    "name": "Paraguay Electronic Invoicing POS Bridge",
    "summary": "Optional Odoo POS channel for the Paraguay fiscal engine",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "einvoice_py"],
    "data": [
        "views/pos_config_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
