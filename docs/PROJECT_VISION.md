# StratAI Project Vision

## Mission

StratAI is an AI-powered strategy and scouting platform for FIRST Robotics Competition (FRC) designed to help teams make better strategic decisions through accurate, explainable, and continuously updated data analysis.

The objective is not simply to make predictions.

The objective is to become the most accurate, trustworthy, and transparent decision-support platform available for FRC teams.

Every engineering decision should improve the platform's accuracy, reliability, scalability, and long-term maintainability.

---

# Core Principles

The following principles are non-negotiable and should guide every future feature.

## Accuracy Above All

Statistical accuracy is always more important than producing impressive-looking outputs.

If the data supports a low-confidence prediction, the system should report low confidence honestly.

The platform must never exaggerate certainty.

---

## Explainability

Every prediction should be explainable.

Users should be able to understand why the system reached a conclusion.

Whenever possible, predictions should be traceable back to the underlying data and calculations.

---

## Data-Driven Decisions

Recommendations must be based on measurable evidence rather than subjective assumptions.

Human observations may be incorporated, but they should be treated as measured inputs rather than hidden heuristics.

---

## Continuous Improvement

The system should improve automatically as additional competition data becomes available.

Historical knowledge should combine with current-season performance to produce increasingly accurate recommendations throughout the season.

---

## Scalability

The architecture should support many years of FRC data without requiring major redesigns.

Adding future seasons or additional data sources should require minimal architectural change.

---

## Maintainability

Correctness, readability, and maintainability are more important than minimizing lines of code.

Simple, understandable solutions are preferred over clever implementations.

---

## Production Quality

Every feature should be designed as though it will eventually support real teams during live competitions.

Temporary shortcuts should be avoided whenever practical.

---

# Long-Term Goals

StratAI should eventually provide:

* Alliance selection assistance
* Match strategy generation
* Win probability prediction
* Team performance analytics
* Robot capability analysis
* Real-time scouting support
* Automated match reports
* Season meta analysis
* Design recommendation assistance
* Historical trend analysis

---

# Data Sources

The platform should integrate multiple sources of competition data.

Current planned sources include:

* The Blue Alliance
* Statbotics
* ScoutRadioz
* Team scouting databases

Additional sources should be easy to integrate using the existing source architecture.

---

# Data Requirements

The system should continuously synchronize new data as competitions progress.

Historical data must never be overwritten.

Raw source data should always be preserved.

Calculated metrics should be reproducible from stored source data.

Every calculated value should be traceable through lineage back to its originating records.

---

# Team Metrics

For every team at every event, the system should calculate:

* Average scoring
* Standard deviation
* Consistency rating
* Good-day performance
* Average performance
* Bad-day performance
* Reliability score
* Defense score
* Feeding score

Defense and feeding ratings are directly measured scouting metrics.

They must never be inferred solely from offensive scoring output.

If insufficient scouting observations exist, the system should explicitly report insufficient data rather than fabricate estimates.

---

# Preseason Analysis

Immediately following each year's game reveal, StratAI should:

* Analyze the released game rules
* Compare the game to historical FRC games
* Identify likely robot archetypes
* Predict which archetypes will dominate the season

Teams should be able to enter information such as:

* Budget
* Manufacturing capability
* Programming resources
* Available mentors
* Available build resources

The platform should estimate:

* Realistic robot ceiling
* Recommended robot archetype
* Features likely achievable

---

# Early Season Analysis

During Weeks 0–1, the system should:

* Analyze early competition results
* Detect emerging strategies
* Detect successful robot designs
* Identify underperforming concepts
* Predict likely meta development

Before every event, the system should:

* Analyze attending teams
* Predict rankings
* Predict alliance captains
* Identify likely playoff contenders

---

# In-Season Learning

As additional matches are played, the system should:

* Continuously update team ratings
* Detect changing strategies
* Detect evolving season meta
* Improve prediction quality
* Recommend strategic adjustments

The system should become increasingly accurate throughout the season.

---

# Match Strategy Engine

Inputs include:

* Alliance composition
* Opposing alliance
* Current event
* Current season data
* Historical performance
* Coach observations

Outputs include:

* Recommended strategy
* Alternative coach-driven strategy
* Robot role assignments
* Defensive assignments
* Scoring priorities
* Realistic win probabilities

Probabilities must be entirely data-driven.

The platform must not bias results toward its own recommendations.

---

# Match Reports

The platform should generate concise pre-match reports containing:

* Alliance roles
* Expected scoring contribution
* Strengths
* Weaknesses
* Defensive threats
* Key risks
* Match flow predictions
* Critical matchups
* Success factors
* Win probability

These reports should help alliances quickly understand the match before entering the field.

---

# Alliance Selection

The platform should generate:

* Pick lists
* Alliance synergy scores
* Alternative alliance combinations
* Predicted playoff success

Selections should consider:

* Scoring ability
* Defense
* Feeding
* Reliability
* Consistency
* Robot role compatibility

The objective is not to rank the highest-scoring robots.

The objective is to maximize playoff success.

---

# Artificial Intelligence Philosophy

Machine learning should perform the core decision making.

Large language models should only assist with natural-language explanations and report generation.

Core calculations, rankings, optimization, and predictions should not depend on paid AI APIs.

This minimizes operating costs while improving reproducibility and scalability.

---

# Definition of Success

StratAI is successful when knowledgeable FRC mentors and strategists consistently agree that its recommendations are accurate, explainable, and genuinely useful during real competitions.

Every phase of development should move the project closer to that goal.