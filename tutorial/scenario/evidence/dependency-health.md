# Downstream dependency health — 2026-05-14 14:00–14:50Z
- Elasticsearch cluster status GREEN throughout; 0 node restarts, 0 shard reallocations.
- Elasticsearch node CPU 45–60% (normal range); JVM heap under 70%.
- Primary orders/users database unaffected; the incident is isolated to the search read path.
- Network between search-api and Elasticsearch: no packet loss, no DNS anomalies observed.
