import logging

from odoo.tests.common import BaseCase


_logger = logging.getLogger(__name__)


class TestRuntimeDependencies(BaseCase):
    def test_lxml_and_xmlsec_are_available(self):
        import lxml
        from lxml import etree
        import xmlsec

        versions = {
            "lxml": lxml.__version__,
            "libxml2": ".".join(str(part) for part in etree.LIBXML_VERSION),
            "xmlsec": xmlsec.__version__,
        }

        _logger.info("XML security runtime versions: %s", versions)
        self.assertTrue(versions["lxml"])
        self.assertTrue(versions["libxml2"])
        self.assertTrue(versions["xmlsec"])
