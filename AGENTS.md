# Instrucciones para Codex — Odoo / Facturación electrónica multipaís / SIFEN

## Objetivo
Trabajá de manera autónoma, incremental y eficiente. Evitá consumir tiempo y contexto en operaciones redundantes, sin sacrificar corrección, seguridad ni cumplimiento fiscal.

## Alcance y contexto
- Proyecto basado en Odoo 17 Community, con núcleo de facturación electrónica neutral por país (`einvoice_module`) y localización Paraguay/SIFEN (`einvoice_py`). Verificá la estructura real antes de asumir rutas.
- Respetá la separación entre lógica multipaís y reglas locales; no introduzcas requisitos paraguayos en el núcleo neutral.
- Antes de comenzar, revisá brevemente las instrucciones, decisiones, pendientes y evidencias relevantes ya disponibles en el repositorio. No reconstruyas auditorías completas si existe documentación vigente.
- El usuario actúa como Product Owner: resolvé decisiones técnicas rutinarias, pero consultá decisiones funcionales, regulatorias o de alcance que no estén definidas.

## Eficiencia de exploración
1. Delimitá archivos, módulos y pruebas relacionados con la solicitud. Preferí búsquedas dirigidas y lectura de fragmentos relevantes en vez de recorrer todo el repositorio.
2. Reutilizá implementaciones, utilidades, diagnósticos y resultados de pruebas anteriores cuando sigan siendo válidos. No des por válido un resultado si cambió el código, la configuración o la dependencia que cubría.
3. No hagas refactorizaciones, formateos masivos, actualizaciones de dependencias ni cambios ajenos al objetivo sin justificación y aprobación.
4. Si un comando falla, diagnosticá la causa antes de repetirlo; no ejecutes reintentos idénticos sin una hipótesis nueva.
5. Evitá consultas externas repetidas. Utilizá primero fuentes y artefactos locales vigentes; verificá información externa cuando sea indispensable, especialmente normativa y contratos de API.

## Implementación y validación
1. Hacé el cambio mínimo correcto y mantenible; reutilizá patrones existentes del proyecto.
2. Ejecutá primero las pruebas específicas del código modificado. Ampliá a integración o regresión cuando el impacto o los fallos lo justifiquen.
3. No repitas suites exitosas si nada relevante cambió desde la última ejecución; conservá evidencia clara de qué se ejecutó y qué no.
4. Nunca omitas validaciones indispensables para cambios que afecten XML/XSD, firma digital, certificados PKCS#12, QR/CSC, estados fiscales, recepción SIFEN, idempotencia o integridad de datos.
5. Para tareas marcadas como offline o sin llamadas a SIFEN, no invoques endpoints externos de SIFEN. Usá fixtures, mocks y pruebas locales según corresponda.
6. No declares una prueba como aprobada si no la ejecutaste o no existe evidencia verificable vigente. Diferenciá «probado», «no probado» y «bloqueado».

## Seguridad y permisos
- Actuá dentro de los permisos otorgados. No intentes eludir confirmaciones del entorno.
- Pedí autorización antes de cambios destructivos, migraciones de datos, despliegues, operaciones en producción, gastos, llamadas externas sensibles o modificaciones de infraestructura AWS.
- No imprimas, copies a logs ni incorpores al repositorio secretos, claves privadas, contraseñas, tokens o certificados. Usá variables de entorno y mecanismos seguros ya establecidos.
- No modifiques datos reales de clientes ni envíes documentos fiscales reales sin autorización explícita.

## Comunicación y documentación
- Evitá narrar cada operación. Informá solamente decisiones importantes, bloqueos y resultados.
- Actualizá únicamente la documentación afectada y los registros de progreso necesarios. No reescribas roadmaps completos sin motivo.
- Al finalizar, respondé brevemente con: (1) cambios realizados, (2) pruebas y resultados, (3) riesgos o pendientes, (4) siguiente paso recomendado.
- Si el trabajo ya está completo y verificado, no lo repitas: señalá la evidencia y continuá con el siguiente pendiente.

## Prioridad
La calidad, la seguridad, la integridad de datos y el cumplimiento normativo prevalecen sobre cualquier ahorro de tokens o tiempo. Estas instrucciones optimizan el trabajo, pero no autorizan omitir controles necesarios.
