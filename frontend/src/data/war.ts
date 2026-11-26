import type { WarFinding } from "../components/WarScorecard";

// 9 BP status flips from the Well-Architected Review delta trace
// (docs/war-diff.md — v1-before → v2-after, Sustainability + Cost Optimization pillars)
export const WAR_FINDINGS: WarFinding[] = [
  {
    bp: "COST05-BP05",
    title: "Select cheapest sufficient resource",
    before: "Partial",
    after: "Implemented",
  },
  {
    bp: "COST06-BP02",
    title: "Right-size compute (arm64 / 256 MB)",
    before: "Not Impl",
    after: "Partial",
  },
  {
    bp: "COST08-BP02",
    title: "Throttle to cap spend (25 r/s, burst 50)",
    before: "Not Impl",
    after: "Implemented",
  },
  {
    bp: "COST10-BP02",
    title: "Cache to eliminate redundant inference",
    before: "Partial",
    after: "Implemented",
  },
  {
    bp: "SUS02-BP03",
    title: "Maximize utilization of provisioned resources",
    before: "Not Impl",
    after: "Partial",
  },
  {
    bp: "SUS03-BP01",
    title: "Optimize software for sustainability",
    before: "Not Impl",
    after: "Implemented",
  },
  {
    bp: "SUS03-BP02",
    title: "Use managed services (DynamoDB TTL cache)",
    before: "Not Impl",
    after: "Partial",
  },
  {
    bp: "SUS03-BP03",
    title: "Implement patterns for optimizing over time",
    before: "Not Impl",
    after: "Partial",
  },
  {
    bp: "SUS03-BP04",
    title: "Choose efficient hardware (Graviton arm64)",
    before: "Not Impl",
    after: "Implemented",
  },
];
