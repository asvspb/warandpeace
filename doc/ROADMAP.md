# ROADMAP

This document tracks strategic milestones.

## Milestone 1 – DB Refactor (SQLite → PostgreSQL)
- [ ] ORM abstraction in `src/db/`  
- [ ] Alembic initialized & first migration  
- [ ] Data migration script  
- [ ] Update `.env.example`, `DEPLOYMENT.md`

## Milestone 2 – Event-Driven Core
- [ ] Add RabbitMQ container  
- [ ] Refactor collector to publish `NewsCollected`  
- [ ] Processor workers subscribe & persist  
- [ ] Bot-API consumes processed events

## Milestone 3 – Personalization MVP
- [ ] User Profile service (FastAPI)  
- [ ] Recommendation engine α  
- [ ] Daily personalized digests

## Milestone 4 – AI Platform Features
- [ ] Gemini 2.x summarization GA  
- [ ] Topic & Sentiment classifiers  
- [ ] Semantic search endpoint

---

## Metrics of Success
1. Delivery latency ≤ 30 s for 100 news/min.  
2. Summarization BLEU +10 % vs baseline.  
3. Digest CTR ≥ 15 %.  
4. Bot-API P95 < 100 ms @ 100 RPS.  
5. Zero-downtime during Postgres failover.
