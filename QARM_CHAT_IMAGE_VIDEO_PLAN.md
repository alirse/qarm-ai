# Qarm unified chat and media roadmap

Status: design and feasibility research only. No media models installed and no media provider connected.

## Product goal
One authenticated owner-facing interface for (1) customizable conversation and coding, (2) image generation/editing, and (3) video generation. Explicit model picker, optional task-aware routing, clear provider availability, limits and prices. Keep existing model integrations. Do not impose an additional broad conversation filter from Qarm; upstream model/service restrictions and law still apply.

## Architecture
- Conversation: existing FCC proxy handles chat/coding models; a new standalone chat UI sits above it.
- Image service: a distinct provider adapter accepting text prompts and optional images, returning task IDs and media URLs. Do not pretend that the existing OpenAI-compatible chat proxy can automatically call arbitrary diffusion checkpoints.
- Video service: a separate asynchronous adapter with job creation, status polling, cancellation, preview, and output expiration. Video generation may take minutes and needs compute or a remote endpoint.
- Model catalog: capability, endpoint/provider, license, size, memory requirements, estimated cost, commercial-use rules, content/consent requirements, and tested status. A model listed on Hugging Face is not proof of free hosted inference.
- Owner preferences: configurable assistant persona and model choices; authenticated account and secure session first. Two-message activation is a UX feature, not standalone authentication.
- Privacy: do not transmit prompts or generated media to outside hosts unless explicitly selected; never commit access tokens, device codes, or session cookies.

## Candidate models to evaluate, not install yet
| Task | Candidates | Notes |
| --- | --- | --- |
| Conversation with customizable style | dphn/Dolphin-Mistral-24B-Venice-Edition; NousResearch/Hermes-4.3-36B | Open weights, provider policy differs from local self-hosting; benchmark truthfulness/tool use as well as responsiveness |
| Coding | Qwen/Qwen3-Coder-Next | Distinct from conversation generation; needs performance and cost validation |
| General images | black-forest-labs/FLUX.1-schnell | Apache 2.0, but large weights and GPU requirements |
| Illustrations, including adult-oriented artistic model ecosystem | OnomaAIResearch/Illustrious-XL-v1.0 | SDXL-family licensing and particular checkpoints need review before use |
| Text/image-to-video | Wan-AI/Wan2.2-TI2V-5B; Lightricks/LTX-2 | Large compute demand; LTX-2 is community-licensed, not generic Apache |

## Constraints
- A Hugging Face model repository may host only downloadable weights; inference can be unavailable, paid, limited or require a GPU.
- Default GitHub Codespaces CPU environments are inappropriate for running several tens-of-GB models at interactive latency.
- Do not promise any provider permits every kind of adult output. Evaluate legitimate consensual adult use, applicable law, terms and model-specific allowances; exclude abusive or non-consensual imagery and content involving minors.
- Media generation is not present in the existing FCC code-session UI; new interfaces and endpoints will be needed.

## Implementation order
1. Finish remote account access and one read-only chat/coding response with a verified model; avoid expanding unfinished authentication code.
2. Build a provider/model capability registry and cost/quota visibility; allow manual choice and graceful missing-key errors.
3. Implement a simple one-screen conversation UI and owner-specific persona settings.
4. Add image adapter and test a no-cost local mock; choose a real provider only after its price and adult-use terms are verified.
5. Add asynchronous video jobs and test mocked queue, progress and delivery before making costly generation calls.
6. Add optional automatic router only after per-task benchmarks and provider price/limits checks.
7. Plan on-demand iPhone/desktop deployment separately; Codespaces is development hosting, not a free guaranteed 24/7 service.

## Acceptance test criteria
- Chat: can ask a question and receive a reply, with the selected live model name shown; report upstream refusals honestly.
- Image: request => async/sync result; saves/retrieves image correctly; clear tool/model attribution and cost.
- Video: progress states and cancellation; output accessible on both iPhone and desktop.
- Reliability: unsupported/unavailable provider never silently falls back to paid service.
- Identity: secret owner activation cannot override authentication or expose admin to public internet.

## Primary project/model references (checked 2026-10-12)
- https://huggingface.co/dphn/Dolphin-Mistral-24B-Venice-Edition
- https://huggingface.co/NousResearch/Hermes-4.3-36B
- https://huggingface.co/Qwen/Qwen3-Coder-Next
- https://huggingface.co/black-forest-labs/FLUX.1-schnell
- https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.0
- https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- https://huggingface.co/Lightricks/LTX-2
