{
    "name": "Fiscal API Foundation",
    "summary": "API key foundation for external fiscal integrations",
    "version": "17.0.1.0.0",
    "category": "Accounting/Accounting",
    "depends": ["base", "einvoice_module"],
    "data": [
        "security/ir.model.access.csv",
        "views/fiscal_api_key_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
