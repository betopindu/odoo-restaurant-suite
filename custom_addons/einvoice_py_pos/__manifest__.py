{
    "name": "Paraguay Electronic Invoicing POS Bridge",
    "summary": "Optional Odoo POS channel for the Paraguay fiscal engine",
    "version": "17.0.1.5.0",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "einvoice_py"],
    "data": [
        "security/ir.model.access.csv",
        "data/pos_fiscal_submission_cron.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "einvoice_py_pos/static/src/js/pos_fiscal_checkout.js",
            "einvoice_py_pos/static/src/xml/pos_fiscal_checkout.xml",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
