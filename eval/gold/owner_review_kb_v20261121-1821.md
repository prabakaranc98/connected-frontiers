# Owner review queue: silver kb_v20261121-1821

Items where the judges split. Write your label in the last column (yes/no for verification;
same/part_or_subtype/different for ER). These become gold.

## Verification (does the quote, in source context, state the claim?)

| id | claim | quote | source | votes | your label |
|---|---|---|---|---|---|
| k0002 | Scale AI —uses_tech→ ElevenLabs | and ElevenLabs for audio functionality | https://scale.com/customers/time | qwen3.5-35b-=Y, inkling-2-sm=N, nemotron-3.5=Y, mistral-smal=N | |
| k0003 | Statista —offers→ AI assistant | AI assistantsResearchStrategy & ConsultingMarketingMedia & PR | https://statista.com/research-ai/ | qwen3.5-35b-=Y, inkling-2-sm=N, nemotron-3.5=Y, mistral-smal=N | |
| k0014 | OluKai AI agent —measured_on→ Customer Satisfaction | Sierra currently delivers a Customer Satisfaction score of about 4.5 out of 5 | https://sierra.ai/customers/olukai | qwen3.5-35b-=N, inkling-2-sm=Y, nemotron-3.5=N, mistral-smal=Y | |
| k0028 | Mantic —cites→ Outcome-based Reinforcement Learning to Predict the Future | Outcome-based Reinforcement Learning to Predict the Future (Turtel et al, 2025) | https://thinkingmachines.ai/news/training-llms-to-predict-world-events/ | qwen3.5-35b-=N, inkling-2-sm=Y, nemotron-3.5=Y, mistral-smal=N | |
| k0089 | Google DeepMind —offers→ Gemini Robotics | Gemini RoboticsPerceive, reason, use tools and interact | https://deepmind.google/research/ | qwen3.5-35b-=N, inkling-2-sm=Y, nemotron-3.5=Y, mistral-smal=N | |
| k0094 | Google DeepMind —offers→ AlphaEvolve | AlphaEvolveDesign advanced algorithms for math and applications in computing | https://deepmind.com/ | qwen3.5-35b-=N, inkling-2-sm=Y, nemotron-3.5=Y, mistral-smal=N | |

## Entity resolution

| id | A | B | type | votes | pipeline said | your label |
|---|---|---|---|---|---|---|
| e0002 | Accel AI | Accel AI Institute | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=different, inkling-2-sm=same | same | |
| e0007 | Genomics plc | Genomics | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=same | same | |
| e0010 | Fable 5.2 | anthropic / claude-fable-5.2 | model | nemotron-3.5=different, mistral-smal=different, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0012 | Pixel | Pixel and Fitbit wearables | technology | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | part_or_subtype | |
| e0013 | Microsoft Copilot | Microsoft AI | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | different | |
| e0014 | Cerebras Wafer Scale Engines | Cerebras Wafer-Scale Engine | technology | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0025 | Aramco Digital | Aramco | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=same, inkling-2-sm=part_or_subtype | part_or_subtype | |
| e0027 | Claude 3.5 Sonnet | Claude-3.5-Sonnet-1022 | model | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=same | same | |
| e0028 | CUDA-Q | CUDA | technology | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | part_or_subtype | |
| e0030 | Lens | Google Lens | technology | nemotron-3.5=different, mistral-smal=same, qwen3.5-35b-=part_or_subtype, inkling-2-sm=same | same | |
| e0033 | FrontierCode | FrontierCode v2.0 | benchmark | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | same | |
| e0036 | impact.com | Impact | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0039 | Azure | OpenAI Azure Service | technology | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=different, inkling-2-sm=part_or_subtype | same | |
| e0042 | Hungry Hungry Hippos | Hungry Hungry Hippos: Towards Language Modeling with State Space Models | paper | nemotron-3.5=different, mistral-smal=different, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0046 | Inkling 2 Mini | unsloth/Inkling-2-Mini-GGUF | model | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | part_or_subtype | |
| e0051 | Granite models | Granite | model | nemotron-3.5=part_or_subtype, mistral-smal=part_or_subtype, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0052 | Management | Manager over workforce management | role | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | part_or_subtype | |
| e0059 | Inkling | unsloth/Inkling-2-Mini-GGUF | model | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | different | |
| e0067 | Amazon | Amazon Bedrock | org | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=part_or_subtype, inkling-2-sm=different | part_or_subtype | |
| e0069 | Earth, Wind & Power | Earth Wind Power | org | nemotron-3.5=different, mistral-smal=same, qwen3.5-35b-=different, inkling-2-sm=same | same | |
| e0072 | Claude’s Constitution | Claude's new constitution | paper | nemotron-3.5=different, mistral-smal=different, qwen3.5-35b-=same, inkling-2-sm=same | same | |
| e0078 | Introducing SynthID Bio | SynthID Bio | paper | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=same, inkling-2-sm=different | same | |
| e0079 | Waze | Waze Map Mate | technology | nemotron-3.5=different, mistral-smal=part_or_subtype, qwen3.5-35b-=different, inkling-2-sm=part_or_subtype | part_or_subtype | |
