# Dawg Path

**Dawg Path** is a safety-aware navigation app built at **DubHacks 2025** to help students and city pedestrians find the *safest* walking routes — not just the fastest ones.  
Traditional navigation tools optimize for distance or time. Dawg Path optimizes for **peace of mind**, guiding users through well-lit, low-risk areas around the University of Washington and beyond.

---

## Inspiration
Walking around campus late at night can be unsettling, especially in poorly lit or isolated areas.  
We wanted to build something that helps students navigate confidently and safely.  
While most navigation apps focus on efficiency, **Dawg Path** focuses on *security and comfort* — letting users “find their way, the safe way.”

---

## What It Does
Dawg Path generates walking routes that minimize exposure to danger zones by:
- Analyzing **road-level danger scores** and **circle-based safety zones** (well-lit or patrolled areas)
- Offering **two modes**: “Prefer Safe” and “Strict Safety”
- Automatically **rerouting around high-risk areas**
- Balancing **distance, duration, and safety** in real-time

---

## How We Built It
- **Backend:** [FastAPI](https://fastapi.tiangolo.com/)  
- **Routing:** [Mapbox Directions API](https://docs.mapbox.com/api/navigation/directions/)  
- **Data:** GTFS transit data for Seattle + custom JSON danger map  
- **Logic:** Composite safety-score model combining danger zones and safety circles  
- **Frontend Visualization:** Mapbox maps and real-time path rendering

Our pipeline fetches multiple walking alternatives, computes a weighted safety score for each route, and ranks paths by a balance of time, distance, and safety.

---

## Challenges
- Integrating **Mapbox**, **GTFS**, and **custom danger data** into a unified routing system  
- Managing **API rate limits** and incomplete geometry data  
- Calibrating the **safety-scoring algorithm** so it reflects real-world intuition  
  (e.g., making sure well-lit roads are safer than dark alleys, not the opposite)  
- Debugging live routes, where every change could drastically alter path output  

---

## Accomplishments
- Built an **end-to-end routing system** that intelligently adjusts for safety  
- Combined multiple geospatial layers into a clean scoring model  
- Delivered a working prototype within the hackathon timeframe  
- Created a project that meaningfully addresses **student safety** and **human-centered navigation**

---

## What We Learned
- How to merge and normalize **multi-format geospatial data**  
- How to design APIs and algorithms for **real-world constraints**  
- The complexity of defining “safety” computationally  
- Effective **team collaboration under time pressure**  
- How design and tech can work together to enhance **personal security**

---

## What’s Next
- Integrate **live incident and safety data** from local agencies  
- Add **crowdsourced safety reports** to improve danger scoring  
- Implement **geofencing and congestion-aware rerouting**  
- Expand coverage to other universities and major cities  

---

## Tech Stack
| Layer | Technology |
|-------|-------------|
| Backend | FastAPI |
| Data Sources | GTFS Seattle Transit, Custom Danger Map (JSON) |
| API Integration | Mapbox Directions API |
| Visualization | Mapbox GL JS |
| Hosting | Render / Vercel |
| Language | Python, JavaScript |

---

## License
This project is open source under the [MIT License](LICENSE).

---

## Contact
Email: muralid@uw.edu, amoghb97@uw.edu, pranav22@uw.edu
