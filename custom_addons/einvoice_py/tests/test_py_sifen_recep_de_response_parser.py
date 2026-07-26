from dataclasses import FrozenInstanceError

from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_sifen_recep_de_response_parser import (
    PySifenRecepDeClassification,
    PySifenRecepDeResponseParser,
)
from odoo.addons.einvoice_py.services.py_sifen_soap_client import (
    PySifenSoapClientResult,
)


class TestPySifenRecepDeResponseParser(BaseCase):
    SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    CDC = "01444444017001001001452822017012515873260988"
    ENDPOINT = "https://sifen-test.example.test/de/ws/sync/recibe.wsdl"

    def setUp(self):
        super().setUp()
        self.parser = PySifenRecepDeResponseParser()

    def test_accepted_response_maps_official_fields(self):
        raw = self._response(
            status="Aprobado",
            results=(("0260", "Autorización del DE satisfactoria"),),
            protocol="1234567890",
        )

        result = self.parser.parse(self._client_result(raw))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.ACCEPTED,
        )
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.raw_response_bytes, raw)
        self.assertEqual(result.response_identifier, self.CDC)
        self.assertEqual(result.request_identifier, "17")
        self.assertEqual(result.processing_datetime, "2026-07-26T12:34:56")
        self.assertEqual(result.result_code, "0260")
        self.assertEqual(
            result.result_message,
            "Autorización del DE satisfactoria",
        )
        self.assertEqual(result.protocol_receipt, "1234567890")
        self.assertEqual(result.cdc, self.CDC)
        self.assertEqual(result.endpoint_url, self.ENDPOINT)
        self.assertEqual(result.elapsed_ms, 125)
        self.assertFalse(result.soap_fault)
        with self.assertRaises(FrozenInstanceError):
            result.http_status = 201

    def test_rejected_and_duplicate_responses_are_distinct(self):
        cases = (
            (
                "0160",
                "XML malformado",
                PySifenRecepDeClassification.REJECTED,
            ),
            (
                "1001",
                "CDC duplicado",
                PySifenRecepDeClassification.DUPLICATE,
            ),
            (
                "1002",
                "Documento electrónico duplicado",
                PySifenRecepDeClassification.DUPLICATE,
            ),
        )
        for code, message, expected in cases:
            with self.subTest(code=code):
                result = self.parser.parse(self._client_result(self._response(
                    status="Rechazado",
                    results=((code, message),),
                )))
                self.assertEqual(result.classification, expected)
                self.assertEqual(result.result_code, code)
                self.assertEqual(result.result_message, message)

    def test_processing_code_from_other_service_is_not_inferred_for_si_recep_de(self):
        result = self.parser.parse(self._client_result(self._response(
            status=None,
            results=(("0361", "Lote en procesamiento"),),
        )))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.UNRECOGNIZED_OFFICIAL_CODE,
        )
        self.assertEqual(result.result_code, "0361")
        self.assertIn("not mapped", result.parse_warnings[-1])
        self.assertIn(
            PySifenRecepDeClassification.PROCESSING_PENDING,
            tuple(PySifenRecepDeClassification),
        )

    def test_unknown_code_is_recoverable_and_preserves_all_official_results(self):
        result = self.parser.parse(self._client_result(self._response(
            status="Estado futuro",
            results=(
                ("9999", "Código futuro"),
                ("9998", "Observación futura"),
            ),
        )))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.UNRECOGNIZED_OFFICIAL_CODE,
        )
        self.assertEqual(result.result_code, "9999")
        self.assertEqual(result.result_message, "Código futuro")
        self.assertEqual(len(result.official_results), 2)
        self.assertTrue(any("not mapped" in item for item in result.parse_warnings))
        self.assertTrue(any("Additional" in item for item in result.parse_warnings))

    def test_soap_12_fault_is_parsed_separately_from_business_rejection(self):
        raw = f"""<env:Envelope xmlns:env="{self.SOAP_NS}">
<env:Body><env:Fault>
<env:Code><env:Value>env:Sender</env:Value><env:Subcode>
<env:Value>sifen:InvalidRequest</env:Value></env:Subcode></env:Code>
<env:Reason><env:Text xml:lang="es">Solicitud inválida</env:Text></env:Reason>
<env:Detail><problem xmlns="urn:test">safe detail</problem></env:Detail>
</env:Fault></env:Body></env:Envelope>""".encode()

        result = self.parser.parse(self._client_result(raw, status=500))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.SOAP_FAULT,
        )
        self.assertTrue(result.soap_fault)
        self.assertEqual(result.soap_fault_code, "env:Sender")
        self.assertEqual(result.soap_fault_subcode, "sifen:InvalidRequest")
        self.assertEqual(result.soap_fault_reason, "Solicitud inválida")
        self.assertIn("safe detail", result.soap_fault_detail)
        self.assertIsNone(result.result_code)

    def test_http_errors_take_precedence_and_preserve_parseable_business_fields(self):
        raw = self._response(
            status="Aprobado",
            results=(("0260", "Aprobado"),),
        )
        result = self.parser.parse(self._client_result(raw, status=503))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.HTTP_ERROR,
        )
        self.assertEqual(result.result_code, "0260")
        self.assertEqual(result.raw_response_bytes, raw)

    def test_http_error_with_non_xml_body_remains_an_http_error(self):
        raw = b"upstream unavailable"
        result = self.parser.parse(self._client_result(raw, status=502))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.HTTP_ERROR,
        )
        self.assertEqual(result.raw_response_bytes, raw)
        self.assertIsNone(result.parsed_xml)

    def test_malformed_and_empty_success_responses_are_distinct(self):
        for raw in (b"", b"<not-xml"):
            with self.subTest(raw=raw):
                result = self.parser.parse(self._client_result(raw))
                self.assertEqual(
                    result.classification,
                    PySifenRecepDeClassification.MALFORMED_RESPONSE,
                )
                self.assertEqual(result.raw_response_bytes, raw)

    def test_missing_body_wrong_namespace_and_missing_wrapper_are_malformed(self):
        cases = (
            f'<env:Envelope xmlns:env="{self.SOAP_NS}"/>'.encode(),
            b'<env:Envelope xmlns:env="urn:not-soap"><env:Body/></env:Envelope>',
            (
                f'<env:Envelope xmlns:env="{self.SOAP_NS}"><env:Body>'
                f'<other xmlns="{self.SIFEN_NS}"/></env:Body></env:Envelope>'
            ).encode(),
            (
                f'<env:Envelope xmlns:env="{self.SOAP_NS}"><env:Body>'
                f'<rRetEnviDe xmlns="urn:not-sifen"/></env:Body></env:Envelope>'
            ).encode(),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                result = self.parser.parse(self._client_result(raw))
                self.assertEqual(
                    result.classification,
                    PySifenRecepDeClassification.MALFORMED_RESPONSE,
                )

    def test_missing_mandatory_processing_datetime_and_cardinality_are_malformed(self):
        missing_datetime = self._response(
            status="Aprobado",
            results=(("0260", "Aprobado"),),
            processing_datetime=None,
        )
        duplicate_protocol = self._response(
            status="Aprobado",
            results=(("0260", "Aprobado"),),
        ).replace(b"</s:rRetEnviDe>", (
            f'<s:rProtDe><s:dFecProc>2026-07-26T12:34:56</s:dFecProc>'
            f'</s:rProtDe></s:rRetEnviDe>'
        ).encode())
        for raw in (missing_datetime, duplicate_protocol):
            with self.subTest(raw=raw[-100:]):
                result = self.parser.parse(self._client_result(raw))
                self.assertEqual(
                    result.classification,
                    PySifenRecepDeClassification.MALFORMED_RESPONSE,
                )

    def test_optional_official_fields_may_be_absent(self):
        raw = f"""<env:Envelope xmlns:env="{self.SOAP_NS}">
<env:Body><s:rRetEnviDe xmlns:s="{self.SIFEN_NS}"><s:rProtDe>
<s:dFecProc>2026-07-26T12:34:56</s:dFecProc>
</s:rProtDe></s:rRetEnviDe></env:Body></env:Envelope>""".encode()

        result = self.parser.parse(self._client_result(raw))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.UNRECOGNIZED_OFFICIAL_CODE,
        )
        self.assertIsNone(result.cdc)
        self.assertIsNone(result.result_code)
        self.assertIsNone(result.protocol_receipt)
        self.assertGreaterEqual(len(result.parse_warnings), 2)

    def test_conflicting_accepted_status_and_duplicate_code_is_malformed(self):
        result = self.parser.parse(self._client_result(self._response(
            status="Aprobado",
            results=(("1001", "CDC duplicado"),),
        )))

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.MALFORMED_RESPONSE,
        )
        self.assertTrue(any("conflicting" in item for item in result.parse_warnings))

    def test_namespace_prefix_is_irrelevant_and_http_200_does_not_imply_acceptance(self):
        first = self.parser.parse(self._client_result(self._response(
            status="Rechazado",
            results=(("0160", "XML malformado"),),
            soap_prefix="env",
            sifen_prefix="s",
        )))
        second = self.parser.parse(self._client_result(self._response(
            status="Rechazado",
            results=(("0160", "XML malformado"),),
            soap_prefix="soap",
            sifen_prefix="ns2",
        )))

        self.assertEqual(first.classification, PySifenRecepDeClassification.REJECTED)
        self.assertEqual(second.classification, first.classification)
        self.assertEqual(second.result_code, first.result_code)
        self.assertEqual(second.cdc, first.cdc)

    def test_identical_input_is_equal_and_repr_does_not_expose_raw_content(self):
        secret = "private-key-secret"
        raw = self._response(
            status="Rechazado",
            results=(("0160", secret),),
        )
        first = self.parser.parse(self._client_result(raw))
        second = self.parser.parse(self._client_result(raw))

        self.assertEqual(first, second)
        self.assertNotIn(secret, repr(first))
        self.assertNotIn(secret, str(first))
        self.assertEqual(first.raw_response_bytes, raw)

    def _client_result(self, raw, *, status=200):
        return PySifenSoapClientResult(
            http_status=status,
            response_headers=(("Content-Type", "application/soap+xml"),),
            raw_response_bytes=raw,
            parsed_xml=None,
            elapsed_ms=125,
            endpoint_url=self.ENDPOINT,
            request_identifier="17",
            category="success",
            error_message="",
        )

    def _response(
        self,
        *,
        status,
        results,
        protocol=None,
        processing_datetime="2026-07-26T12:34:56",
        soap_prefix="env",
        sifen_prefix="s",
    ):
        status_xml = (
            f"<{sifen_prefix}:dEstRes>{status}</{sifen_prefix}:dEstRes>"
            if status is not None
            else ""
        )
        date_xml = (
            f"<{sifen_prefix}:dFecProc>{processing_datetime}"
            f"</{sifen_prefix}:dFecProc>"
            if processing_datetime is not None
            else ""
        )
        protocol_xml = (
            f"<{sifen_prefix}:dProtAut>{protocol}</{sifen_prefix}:dProtAut>"
            if protocol is not None
            else ""
        )
        results_xml = "".join(
            f"<{sifen_prefix}:gResProc>"
            f"<{sifen_prefix}:dCodRes>{code}</{sifen_prefix}:dCodRes>"
            f"<{sifen_prefix}:dMsgRes>{message}</{sifen_prefix}:dMsgRes>"
            f"</{sifen_prefix}:gResProc>"
            for code, message in results
        )
        return (
            f'<{soap_prefix}:Envelope xmlns:{soap_prefix}="{self.SOAP_NS}">'
            f"<{soap_prefix}:Header/><{soap_prefix}:Body>"
            f'<{sifen_prefix}:rRetEnviDe xmlns:{sifen_prefix}="{self.SIFEN_NS}">'
            f"<{sifen_prefix}:rProtDe><{sifen_prefix}:Id>{self.CDC}"
            f"</{sifen_prefix}:Id>{date_xml}"
            f"<{sifen_prefix}:dDigVal>ZGlnZXN0</{sifen_prefix}:dDigVal>"
            f"{status_xml}{protocol_xml}{results_xml}"
            f"</{sifen_prefix}:rProtDe></{sifen_prefix}:rRetEnviDe>"
            f"</{soap_prefix}:Body></{soap_prefix}:Envelope>"
        ).encode()
