{
    "name": "Restaurant KDS",
    "summary": "Kitchen Display System for Odoo POS Restaurant",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "pos_restaurant"],
    "data": [
        "security/ir.model.access.csv",
        "views/kitchen_order_sequence.xml",
        "views/pos_config_views.xml",
        "views/kitchen_order_views.xml",
        "views/kitchen_order_cron.xml",
        "views/kitchen_display.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kds_module/static/src/css/kitchen.css",
        ],
        "web.assets_frontend": [
            "kds_module/static/src/css/kitchen.css",
            "kds_module/static/src/js/kitchen_display.js",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
