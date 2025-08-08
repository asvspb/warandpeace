# ARCHITECTURE

> Skeleton template – fill in details as implementation evolves.

## 1. Overview
Brief description of platform goals and high-level structure.

---

## 2. C4 Model

### 2.1 Context Diagram
*Who interacts with the system?*

### 2.2 Container Diagram
| Container | Technology | Responsibility |
|-----------|------------|----------------|
| collector | Python / aiohttp | Crawls & collects raw articles |
| queue     | RabbitMQ         | Buffer & back-pressure          |
| processor | Python workers   | Dedup, summarise, classify      |
| bot-api   | python-telegram-bot | User interaction             |
| personalizer | FastAPI / ML  | Recommendations & digests       |
| storage-sql | PostgreSQL     | Structured data                |
| storage-nosql | MongoDB / S3 | Full texts, images              |
| cache     | Redis           | Hot data & rate-limits          |
| monitoring | Prometheus/Grafana | Metrics & alerts             |

### 2.3 Component Diagram (inside _processor_)
1. **Deduplicator**
2. **Summarizer**
3. **Classifier**
4. **SentimentAnalyzer**
5. **EventPublisher**

### 2.4 Code Map
Link packages/modules to components once refactor is complete.

---

## 3. Data Flow
End-to-end path of a news item from source to Telegram (add sequence diagram).

---

## 4. Deployment Topology
• Docker-Compose for local dev.  
• Kubernetes Helm chart for prod.

---

## 5. Operational Concerns
* Logging & tracing
* Backups & disaster recovery
* CI/CD pipeline steps

---

## 6. Glossary
| Term | Meaning |
|------|---------|
| Event Bus | RabbitMQ topic exchange |
| Digest | Personalized collection of summaries |
