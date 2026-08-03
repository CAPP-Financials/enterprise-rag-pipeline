/**
 * VeriGreen ESG Validation Portal — Results Dashboard
 * Design: Carbon Ledger — dark-mode financial audit terminal
 * Colors: Deep charcoal-blue bg, electric emerald accent
 * Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (code/IDs)
 *
 * Data flow:
 *  1. sessionStorage["vg_job_<jobId>"] holds the submitted claims array
 *  2. Page polls /api/results/:jobId (Make.com query webhook) every 8s
 *  3. Until real scores arrive, shows "Processing…" skeleton per claim
 *  4. Once scores arrive, renders full score cards with 5 indicators
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, useLocation } from "wouter";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ArrowLeft,
  RefreshCw,
  Download,
  BarChart3,
  Leaf,
  Zap,
  Droplets,
  Users,
  Shield,
  Globe,
  Recycle,
  ChevronDown,
  ChevronUp,
  Info,
} from "lucide-react";
import { toast } from "sonner";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Claim {
  raw_text: string;
  category: string;
  company_id: string;
  year: string;
  id_int: number;
  job_id: string;
}

interface ClaimScore {
  id_int: number;
  raw_text: string;
  category: string;
  substantiation_score: number;
  vague_language: boolean;
  quantification: boolean;
  baseline: boolean;
  time_bound: boolean;
  third_party_verification: boolean;
  greenwashing_risk: "low" | "medium" | "high";
  processing?: boolean;
}

interface JobData {
  jobId: string;
  companyName: string;
  reportingYear: string;
  reportType: string;
  claimCount: number;
  claims: Claim[];
  submittedAt: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const RESULTS_WEBHOOK_URL = import.meta.env.VITE_RESULTS_WEBHOOK_URL || "";

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  "Climate & Emissions": Leaf,
  "Energy": Zap,
  "Water": Droplets,
  "Social & Labour": Users,
  "Governance": Shield,
  "Supply Chain": Globe,
  "Circular Economy": Recycle,
  "Biodiversity": Leaf,
};

const CATEGORY_COLORS: Record<string, string> = {
  "Climate & Emissions": "oklch(0.75 0.18 150)",
  "Energy": "oklch(0.82 0.18 85)",
  "Water": "oklch(0.72 0.15 220)",
  "Social & Labour": "oklch(0.75 0.15 280)",
  "Governance": "oklch(0.78 0.12 200)",
  "Supply Chain": "oklch(0.75 0.15 60)",
  "Circular Economy": "oklch(0.72 0.18 170)",
  "Biodiversity": "oklch(0.70 0.20 130)",
};

const INDICATOR_LABELS: Record<string, string> = {
  vague_language: "No Vague Language",
  quantification: "Quantified Metric",
  baseline: "Baseline Reference",
  time_bound: "Time-Bound Target",
  third_party_verification: "Third-Party Verified",
};

const INDICATOR_DESCRIPTIONS: Record<string, string> = {
  vague_language: "Claim uses specific, measurable language rather than vague terms like 'committed to' or 'working towards'",
  quantification: "Claim includes a specific number, percentage, or measurable quantity",
  baseline: "Claim references a baseline year or starting point for comparison",
  time_bound: "Claim specifies a target year, deadline, or time horizon",
  third_party_verification: "Claim references an external audit, certification, or third-party verification",
};

// ─── Utility functions ────────────────────────────────────────────────────────

function scoreToRisk(score: number): "low" | "medium" | "high" {
  if (score >= 4) return "low";
  if (score >= 2) return "medium";
  return "high";
}

function scoreToLabel(score: number): string {
  if (score === 5) return "Fully Substantiated";
  if (score === 4) return "Well Substantiated";
  if (score === 3) return "Partially Substantiated";
  if (score === 2) return "Weakly Substantiated";
  if (score === 1) return "Barely Substantiated";
  return "Greenwashing Risk";
}

function scoreToColor(score: number): string {
  if (score >= 4) return "oklch(0.75 0.18 150)";
  if (score >= 2) return "oklch(0.82 0.18 85)";
  return "oklch(0.65 0.22 25)";
}

function riskBadgeStyle(risk: "low" | "medium" | "high") {
  if (risk === "low") return { bg: "oklch(0.75 0.18 150 / 0.12)", color: "oklch(0.75 0.18 150)", label: "Low Risk" };
  if (risk === "medium") return { bg: "oklch(0.82 0.18 85 / 0.12)", color: "oklch(0.82 0.18 85)", label: "Medium Risk" };
  return { bg: "oklch(0.65 0.22 25 / 0.12)", color: "oklch(0.65 0.22 25)", label: "High Risk" };
}

// ─── Skeleton claim card ──────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border/30 p-5 animate-pulse"
      style={{ background: "oklch(0.15 0.008 240)" }}>
      <div className="flex items-start justify-between mb-3">
        <div className="h-4 w-24 rounded" style={{ background: "oklch(1 0 0 / 0.08)" }} />
        <div className="h-5 w-20 rounded-full" style={{ background: "oklch(1 0 0 / 0.08)" }} />
      </div>
      <div className="space-y-2 mb-4">
        <div className="h-3 w-full rounded" style={{ background: "oklch(1 0 0 / 0.06)" }} />
        <div className="h-3 w-4/5 rounded" style={{ background: "oklch(1 0 0 / 0.06)" }} />
        <div className="h-3 w-3/5 rounded" style={{ background: "oklch(1 0 0 / 0.06)" }} />
      </div>
      <div className="flex gap-2">
        {[1,2,3,4,5].map(i => (
          <div key={i} className="h-7 flex-1 rounded" style={{ background: "oklch(1 0 0 / 0.06)" }} />
        ))}
      </div>
    </div>
  );
}

// ─── Claim score card ─────────────────────────────────────────────────────────

function ClaimCard({ claim, index }: { claim: ClaimScore; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const risk = riskBadgeStyle(claim.greenwashing_risk);
  const CategoryIcon = CATEGORY_ICONS[claim.category] || Leaf;
  const catColor = CATEGORY_COLORS[claim.category] || "oklch(0.82 0.22 150)";

  const indicators = [
    { key: "vague_language", value: claim.vague_language },
    { key: "quantification", value: claim.quantification },
    { key: "baseline", value: claim.baseline },
    { key: "time_bound", value: claim.time_bound },
    { key: "third_party_verification", value: claim.third_party_verification },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.04, ease: [0.23, 1, 0.32, 1] }}
      className="rounded-xl border border-border/30 overflow-hidden"
      style={{ background: "oklch(0.15 0.008 240)" }}
    >
      {/* Card header */}
      <div className="p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
              style={{ background: `${catColor}20` }}>
              <CategoryIcon className="w-3.5 h-3.5" style={{ color: catColor }} />
            </div>
            <span className="text-xs font-medium truncate" style={{ color: catColor }}>
              {claim.category}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: risk.bg, color: risk.color }}>
              {risk.label}
            </span>
          </div>
        </div>

        {/* Claim text */}
        <p className="text-sm leading-relaxed text-foreground/90 mb-4 line-clamp-3">
          "{claim.raw_text}"
        </p>

        {/* Score bar */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-muted-foreground">Substantiation Score</span>
              <span className="text-sm font-bold mono" style={{ color: scoreToColor(claim.substantiation_score) }}>
                {claim.substantiation_score}/5
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "oklch(1 0 0 / 0.08)" }}>
              <motion.div
                className="h-full rounded-full"
                style={{ background: scoreToColor(claim.substantiation_score) }}
                initial={{ width: 0 }}
                animate={{ width: `${(claim.substantiation_score / 5) * 100}%` }}
                transition={{ duration: 0.6, delay: index * 0.04 + 0.2, ease: [0.23, 1, 0.32, 1] }}
              />
            </div>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-xs font-medium" style={{ color: scoreToColor(claim.substantiation_score) }}>
              {scoreToLabel(claim.substantiation_score)}
            </p>
          </div>
        </div>

        {/* 5 indicator pills */}
        <div className="flex flex-wrap gap-1.5">
          {indicators.map(({ key, value }) => (
            <div
              key={key}
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs"
              style={{
                background: value ? "oklch(0.75 0.18 150 / 0.1)" : "oklch(1 0 0 / 0.04)",
                border: `1px solid ${value ? "oklch(0.75 0.18 150 / 0.3)" : "oklch(1 0 0 / 0.08)"}`,
              }}
              title={INDICATOR_DESCRIPTIONS[key]}
            >
              {value ? (
                <CheckCircle2 className="w-3 h-3 flex-shrink-0" style={{ color: "oklch(0.75 0.18 150)" }} />
              ) : (
                <XCircle className="w-3 h-3 flex-shrink-0" style={{ color: "oklch(0.5 0 0)" }} />
              )}
              <span style={{ color: value ? "oklch(0.75 0.18 150)" : "oklch(0.5 0 0)" }}>
                {INDICATOR_LABELS[key]}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Expandable detail */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-5 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors border-t border-border/20"
        style={{ background: "oklch(1 0 0 / 0.02)" }}
      >
        <span>Indicator breakdown</span>
        {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-4 pt-3 space-y-3 border-t border-border/20">
              {indicators.map(({ key, value }) => (
                <div key={key} className="flex items-start gap-3">
                  <div className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                    style={{ background: value ? "oklch(0.75 0.18 150 / 0.15)" : "oklch(1 0 0 / 0.06)" }}>
                    {value ? (
                      <CheckCircle2 className="w-3 h-3" style={{ color: "oklch(0.75 0.18 150)" }} />
                    ) : (
                      <XCircle className="w-3 h-3" style={{ color: "oklch(0.5 0 0)" }} />
                    )}
                  </div>
                  <div>
                    <p className="text-xs font-medium mb-0.5" style={{
                      color: value ? "oklch(0.75 0.18 150)" : "oklch(0.5 0 0)"
                    }}>
                      {INDICATOR_LABELS[key]}
                    </p>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {INDICATOR_DESCRIPTIONS[key]}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Main Results page ────────────────────────────────────────────────────────

export default function Results() {
  const { jobId } = useParams<{ jobId: string }>();
  const [, navigate] = useLocation();

  const [jobData, setJobData] = useState<JobData | null>(null);
  const [scores, setScores] = useState<ClaimScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [lastPolled, setLastPolled] = useState<Date | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [filterRisk, setFilterRisk] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"score_asc" | "score_desc" | "category">("score_desc");
  const [pollingAttempts, setPollingAttempts] = useState(0);

  // ── Load job data from sessionStorage ──────────────────────────────────────
  useEffect(() => {
    if (!jobId) return;
    const raw = sessionStorage.getItem(`vg_job_${jobId}`);
    if (raw) {
      try {
        const data: JobData = JSON.parse(raw);
        setJobData(data);
        // Pre-populate with processing placeholders
        const placeholders: ClaimScore[] = data.claims.map(c => ({
          id_int: c.id_int,
          raw_text: c.raw_text,
          category: c.category,
          substantiation_score: 0,
          vague_language: false,
          quantification: false,
          baseline: false,
          time_bound: false,
          third_party_verification: false,
          greenwashing_risk: "high",
          processing: true,
        }));
        setScores(placeholders);
      } catch {
        // ignore parse error
      }
    }
    setLoading(false);
  }, [jobId]);

  // ── Poll results webhook ────────────────────────────────────────────────────
  const fetchResults = useCallback(async () => {
    if (!jobId || !RESULTS_WEBHOOK_URL) return false;
    setPolling(true);
    try {
      const res = await fetch(`${RESULTS_WEBHOOK_URL}?job_id=${encodeURIComponent(jobId)}`);
      if (!res.ok) return false;
      const data = await res.json();
      if (data.results && Array.isArray(data.results) && data.results.length > 0) {
        const mapped: ClaimScore[] = data.results.map((r: Record<string, unknown>) => ({
          id_int: r.id as number,
          raw_text: (r.payload as Record<string, unknown>)?.raw_text as string || "",
          category: (r.payload as Record<string, unknown>)?.category as string || "General",
          substantiation_score: (r.payload as Record<string, unknown>)?.substantiation_score as number || 0,
          vague_language: Boolean((r.payload as Record<string, unknown>)?.vague_language),
          quantification: Boolean((r.payload as Record<string, unknown>)?.quantification),
          baseline: Boolean((r.payload as Record<string, unknown>)?.baseline),
          time_bound: Boolean((r.payload as Record<string, unknown>)?.time_bound),
          third_party_verification: Boolean((r.payload as Record<string, unknown>)?.third_party_verification),
          greenwashing_risk: scoreToRisk((r.payload as Record<string, unknown>)?.substantiation_score as number || 0),
          processing: false,
        }));
        setScores(mapped);
        setLastPolled(new Date());
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      setPolling(false);
    }
  }, [jobId]);

  // ── Auto-poll every 8s for up to 12 attempts (96s total) ──────────────────
  useEffect(() => {
    if (!RESULTS_WEBHOOK_URL) return;
    const interval = setInterval(async () => {
      setPollingAttempts(a => a + 1);
      const found = await fetchResults();
      if (found || pollingAttempts >= 12) clearInterval(interval);
    }, 8000);
    // Initial poll after 5s
    const initial = setTimeout(() => fetchResults(), 5000);
    return () => { clearInterval(interval); clearTimeout(initial); };
  }, [fetchResults, pollingAttempts]);

  // ── Derived stats ──────────────────────────────────────────────────────────
  const realScores = scores.filter(s => !s.processing);
  const avgScore = realScores.length > 0
    ? realScores.reduce((a, b) => a + b.substantiation_score, 0) / realScores.length
    : null;
  const highRiskCount = realScores.filter(s => s.greenwashing_risk === "high").length;
  const fullySubstantiated = realScores.filter(s => s.substantiation_score >= 4).length;

  const categories = Array.from(new Set(scores.map(s => s.category)));

  const filteredScores = scores
    .filter(s => filterCategory === "all" || s.category === filterCategory)
    .filter(s => filterRisk === "all" || s.greenwashing_risk === filterRisk)
    .sort((a, b) => {
      if (sortBy === "score_desc") return b.substantiation_score - a.substantiation_score;
      if (sortBy === "score_asc") return a.substantiation_score - b.substantiation_score;
      return a.category.localeCompare(b.category);
    });

  const processingCount = scores.filter(s => s.processing).length;
  const isProcessing = processingCount > 0 && !RESULTS_WEBHOOK_URL;

  // ── Download report ────────────────────────────────────────────────────────
  const downloadReport = () => {
    if (!jobData) return;
    const lines = [
      `VeriGreen ESG Validation Report`,
      `================================`,
      `Company: ${jobData.companyName}`,
      `Year: ${jobData.reportingYear}`,
      `Report Type: ${jobData.reportType}`,
      `Job ID: ${jobId}`,
      `Submitted: ${new Date(jobData.submittedAt).toLocaleString()}`,
      `Total Claims: ${jobData.claimCount}`,
      ``,
      avgScore !== null ? `Average Score: ${avgScore.toFixed(1)}/5` : `Scores: Processing...`,
      `High Risk Claims: ${highRiskCount}`,
      `Fully Substantiated: ${fullySubstantiated}`,
      ``,
      `CLAIM DETAILS`,
      `=============`,
      ...realScores.map((s, i) => [
        ``,
        `[${i + 1}] ${s.category} — Score: ${s.substantiation_score}/5 (${scoreToLabel(s.substantiation_score)})`,
        `Risk: ${s.greenwashing_risk.toUpperCase()}`,
        `Text: "${s.raw_text}"`,
        `Indicators:`,
        `  ✓ No Vague Language: ${s.vague_language ? "Yes" : "No"}`,
        `  ✓ Quantified Metric: ${s.quantification ? "Yes" : "No"}`,
        `  ✓ Baseline Reference: ${s.baseline ? "Yes" : "No"}`,
        `  ✓ Time-Bound Target: ${s.time_bound ? "Yes" : "No"}`,
        `  ✓ Third-Party Verified: ${s.third_party_verification ? "Yes" : "No"}`,
      ].join("\n")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `verigreen-report-${jobId}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Report downloaded.");
  };

  // ─── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 rounded-full border-2 border-primary border-t-transparent animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground text-sm">Loading results…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background grid-bg flex flex-col">

      {/* ── Header ── */}
      <header className="border-b border-border/50 backdrop-blur-sm sticky top-0 z-50"
        style={{ background: "oklch(0.12 0.008 240 / 0.9)" }}>
        <div className="container flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <img
              src="/manus-storage/verigreen-logo_ef972fd4.png"
              alt="VeriGreen"
              className="h-8 w-8 object-contain"
            />
            <div>
              <span className="font-bold text-sm tracking-tight" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                VeriGreen
              </span>
              <span className="text-muted-foreground text-xs ml-2 hidden sm:inline">ESG Validation Results</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {RESULTS_WEBHOOK_URL && (
              <button
                onClick={() => fetchResults()}
                disabled={polling}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${polling ? "animate-spin" : ""}`} />
                {lastPolled ? `Updated ${lastPolled.toLocaleTimeString()}` : "Refresh"}
              </button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/")}
              className="gap-1.5 text-xs"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              New Report
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 container py-8">

        {/* ── Job info banner ── */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-border/40 p-5 mb-6 flex flex-wrap items-center justify-between gap-4"
          style={{ background: "oklch(0.15 0.008 240)" }}
        >
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-widest mono mb-1">Validation Job</p>
            <h1 className="text-xl font-bold" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              {jobData?.companyName || "ESG Report"}
            </h1>
            <div className="flex flex-wrap items-center gap-3 mt-1">
              <span className="text-xs text-muted-foreground mono">
                {jobData?.reportingYear} · {jobData?.reportType}
              </span>
              <span className="text-xs mono" style={{ color: "oklch(0.82 0.22 150)" }}>
                {jobId}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isProcessing && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
                style={{ background: "oklch(0.82 0.18 85 / 0.1)", border: "1px solid oklch(0.82 0.18 85 / 0.3)" }}>
                <Clock className="w-3.5 h-3.5 animate-pulse" style={{ color: "oklch(0.82 0.18 85)" }} />
                <span className="text-xs" style={{ color: "oklch(0.82 0.18 85)" }}>
                  Pipeline processing {processingCount} claims…
                </span>
              </div>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={downloadReport}
              disabled={realScores.length === 0}
              className="gap-1.5 text-xs"
            >
              <Download className="w-3.5 h-3.5" />
              Export
            </Button>
          </div>
        </motion.div>

        {/* ── Summary stats ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {[
            {
              label: "Total Claims",
              value: scores.length,
              sub: `${processingCount > 0 ? `${processingCount} processing` : "all scored"}`,
              color: "oklch(0.82 0.22 150)",
              icon: BarChart3,
            },
            {
              label: "Avg. Score",
              value: avgScore !== null ? `${avgScore.toFixed(1)}/5` : "—",
              sub: avgScore !== null ? scoreToLabel(Math.round(avgScore)) : "processing…",
              color: avgScore !== null ? scoreToColor(avgScore) : "oklch(0.5 0 0)",
              icon: CheckCircle2,
            },
            {
              label: "High Risk",
              value: highRiskCount,
              sub: `${scores.length > 0 ? Math.round((highRiskCount / scores.length) * 100) : 0}% of claims`,
              color: "oklch(0.65 0.22 25)",
              icon: AlertTriangle,
            },
            {
              label: "Substantiated",
              value: fullySubstantiated,
              sub: `score ≥ 4/5`,
              color: "oklch(0.75 0.18 150)",
              icon: Shield,
            },
          ].map((stat, i) => {
            const Icon = stat.icon;
            return (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06 }}
                className="rounded-xl border border-border/30 p-4"
                style={{ background: "oklch(0.15 0.008 240)" }}
              >
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-muted-foreground">{stat.label}</p>
                  <Icon className="w-4 h-4 text-muted-foreground" />
                </div>
                <p className="text-2xl font-bold mono" style={{ color: stat.color, fontFamily: "'Space Grotesk', sans-serif" }}>
                  {stat.value}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">{stat.sub}</p>
              </motion.div>
            );
          })}
        </div>

        {/* ── Category breakdown bar ── */}
        {realScores.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="rounded-xl border border-border/30 p-5 mb-6"
            style={{ background: "oklch(0.15 0.008 240)" }}
          >
            <p className="text-xs text-muted-foreground uppercase tracking-widest mono mb-4">Score by Category</p>
            <div className="space-y-3">
              {categories.map(cat => {
                const catScores = realScores.filter(s => s.category === cat);
                if (catScores.length === 0) return null;
                const avg = catScores.reduce((a, b) => a + b.substantiation_score, 0) / catScores.length;
                const color = CATEGORY_COLORS[cat] || "oklch(0.82 0.22 150)";
                const CatIcon = CATEGORY_ICONS[cat] || Leaf;
                return (
                  <div key={cat} className="flex items-center gap-3">
                    <div className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0"
                      style={{ background: `${color}20` }}>
                      <CatIcon className="w-3 h-3" style={{ color }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium truncate">{cat}</span>
                        <span className="text-xs mono ml-2 flex-shrink-0" style={{ color }}>
                          {avg.toFixed(1)}/5 · {catScores.length} claim{catScores.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "oklch(1 0 0 / 0.08)" }}>
                        <motion.div
                          className="h-full rounded-full"
                          style={{ background: color }}
                          initial={{ width: 0 }}
                          animate={{ width: `${(avg / 5) * 100}%` }}
                          transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}

        {/* ── Filters + sort ── */}
        <div className="flex flex-wrap items-center gap-3 mb-5">
          <p className="text-xs text-muted-foreground">Filter:</p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setFilterCategory("all")}
              className="text-xs px-2.5 py-1 rounded-full transition-colors"
              style={{
                background: filterCategory === "all" ? "oklch(0.82 0.22 150)" : "oklch(1 0 0 / 0.06)",
                color: filterCategory === "all" ? "oklch(0.1 0.008 240)" : "oklch(0.6 0 0)",
              }}
            >
              All
            </button>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setFilterCategory(cat)}
                className="text-xs px-2.5 py-1 rounded-full transition-colors"
                style={{
                  background: filterCategory === cat ? CATEGORY_COLORS[cat] || "oklch(0.82 0.22 150)" : "oklch(1 0 0 / 0.06)",
                  color: filterCategory === cat ? "oklch(0.1 0.008 240)" : "oklch(0.6 0 0)",
                }}
              >
                {cat}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <p className="text-xs text-muted-foreground">Risk:</p>
            {["all", "high", "medium", "low"].map(r => (
              <button
                key={r}
                onClick={() => setFilterRisk(r)}
                className="text-xs px-2.5 py-1 rounded-full capitalize transition-colors"
                style={{
                  background: filterRisk === r ? "oklch(1 0 0 / 0.12)" : "oklch(1 0 0 / 0.04)",
                  color: filterRisk === r ? "oklch(0.9 0 0)" : "oklch(0.5 0 0)",
                  border: filterRisk === r ? "1px solid oklch(1 0 0 / 0.2)" : "1px solid transparent",
                }}
              >
                {r}
              </button>
            ))}
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as typeof sortBy)}
              className="text-xs px-2 py-1 rounded-md border border-border/30 bg-transparent text-muted-foreground"
            >
              <option value="score_desc">Score ↓</option>
              <option value="score_asc">Score ↑</option>
              <option value="category">Category</option>
            </select>
          </div>
        </div>

        {/* ── No job data state ── */}
        {!jobData && !loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="rounded-xl border border-border/30 p-12 text-center"
            style={{ background: "oklch(0.15 0.008 240)" }}
          >
            <Info className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
            <h2 className="text-lg font-bold mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              Job not found
            </h2>
            <p className="text-muted-foreground text-sm mb-5 max-w-sm mx-auto">
              Results are stored in your browser session. If you refreshed the page, the session data may have been cleared.
            </p>
            <Button onClick={() => navigate("/")} className="gap-2">
              <ArrowLeft className="w-4 h-4" />
              Submit a New Report
            </Button>
          </motion.div>
        )}

        {/* ── Processing notice (no webhook configured) ── */}
        {jobData && !RESULTS_WEBHOOK_URL && processingCount > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border p-4 mb-5 flex items-start gap-3"
            style={{
              background: "oklch(0.82 0.18 85 / 0.06)",
              borderColor: "oklch(0.82 0.18 85 / 0.3)",
            }}
          >
            <Clock className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "oklch(0.82 0.18 85)" }} />
            <div>
              <p className="text-sm font-medium mb-0.5" style={{ color: "oklch(0.82 0.18 85)" }}>
                Pipeline is processing your claims
              </p>
              <p className="text-xs text-muted-foreground">
                {processingCount} claim{processingCount !== 1 ? "s" : ""} are being scored by Gemini 2.5 Flash and embedded by Mistral.
                Results are persisted to the Qdrant audit database. Configure <code className="mono text-xs">VITE_RESULTS_WEBHOOK_URL</code> to
                enable live score retrieval on this page.
              </p>
            </div>
          </motion.div>
        )}

        {/* ── Claim cards grid ── */}
        {jobData && (
          <div className="grid gap-4 lg:grid-cols-2">
            {filteredScores.map((claim, i) =>
              claim.processing ? (
                <SkeletonCard key={claim.id_int} />
              ) : (
                <ClaimCard key={claim.id_int} claim={claim} index={i} />
              )
            )}
          </div>
        )}

        {/* ── Empty filter state ── */}
        {jobData && filteredScores.length === 0 && scores.length > 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground text-sm">No claims match the current filters.</p>
            <button
              onClick={() => { setFilterCategory("all"); setFilterRisk("all"); }}
              className="text-xs mt-2 underline text-muted-foreground hover:text-foreground"
            >
              Clear filters
            </button>
          </div>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-border/30 py-4">
        <div className="container flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            VeriGreen ESG Validation Portal · Built on Make.com
          </p>
          <p className="text-xs text-muted-foreground">
            Threshold scoring coming in v2
          </p>
        </div>
      </footer>
    </div>
  );
}
