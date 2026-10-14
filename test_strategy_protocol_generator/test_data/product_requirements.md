# Product Requirements: AI Health Assistant

## Overview
The product is a clinician-facing AI assistant that helps summarize patient data and draft care recommendations. The assistant must support secure access, clear explanations, and auditability.

## Functional Requirements
1. The system must allow clinicians to upload patient notes and retrieve a summary.
2. The assistant must classify each recommendation as low, medium, or high confidence.
3. The system must provide citations to the source text used for each recommendation.
4. The system must support a feedback loop where clinicians can flag inaccurate or unsafe outputs.
5. The product must detect unsupported or uncertain recommendations and require review.

## Non-Functional Requirements
- Response time for standard summary requests must be under 10 seconds.
- Data must be encrypted in transit and at rest.
- Logs must be retained for audit and safety review.
- The application must comply with healthcare data privacy requirements.

## Safety Requirements
- Medical advice must be clearly labeled as informational and not a substitute for clinician judgment.
- The system must not generate emergency treatment instructions without human review.
- Hallucinated or unsupported clinical claims must be blocked or flagged.
