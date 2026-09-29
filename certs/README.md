# Сертификат для API MAX

`russian_trusted_root_ca.pem` — открытый корневой сертификат Russian Trusted Root CA Минцифры России. Источник: [Госуслуги / gu-st.ru](https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt). SHA-256 отпечаток DER: `D26D2D0231B7C39F92CC738512BA54103519E4405D68B5BD703E9788CA8ECF31`. Проверен при добавлении 29 сентября 2026 г.

Клиент MAX добавляет этот корень **только** в TLS-контекст запросов к `platform-api2.max.ru`; системное хранилище сертификатов он не меняет. Проверка имени сервера и цепочки остаётся включённой. При необходимости укажите другой PEM-файл через `MAX_CA_BUNDLE`.
