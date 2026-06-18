FROM odoo:17.0

USER root

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libxmlsec1 \
        libxmlsec1-openssl \
        python3-xmlsec \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -c "import lxml, xmlsec; print(f'lxml={lxml.__version__} xmlsec={xmlsec.__version__}')"

USER odoo
