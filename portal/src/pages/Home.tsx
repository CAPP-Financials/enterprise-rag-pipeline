/**
 * VeriGreen ESG Validation Portal — Home Page
 * Design: Carbon Ledger — dark-mode financial audit terminal
 * Colors: Deep charcoal-blue bg, electric emerald accent
 * Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (code/IDs)
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import {
  Upload,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  ChevronRight,
  Zap,
  Database,
  Brain,
  Layers,
  Shield,
  BarChart3,
} from "lucide-react";
import { nanoid } from "nanoid";
import { parseEsgDocument } from "@/lib/esgParser";

// ─── Types ────────────────────────────────────────────────────────────────────

type FormState = "idle" | "ready" | "submitting" | "parsing" | "success" | "error";

interface FormData {
  companyName: string;
  reportingYear: string;
  reportType: string;
  file: File | null;
}

// ─── Pipeline stages ──────────────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { id: 1, icon: Upload,       label: "Ingest",    desc: "Document received" },
  { id: 2, icon: FileText,     label: "Parse",     desc: "Make AI Extractor" },
  { id: 3, icon: Brain,        label: "Extract",   desc: "Gemini 2.5 Flash" },
  { id: 4, icon: Layers,       label: "Iterate",   desc: "Per-claim fan-out" },
  { id: 5, icon: Shield,       label: "Score",     desc: "Substantiation rubric" },
  { id: 6, icon: Zap,          label: "Embed",     desc: "Mistral Embed-2312" },
  { id: 7, icon: Database,     label: "Persist",   desc: "Supabase upsert" },
  { id: 8, icon: BarChart3,    label: "Report",    desc: "Validation complete" },
];

const YEARS = Array.from({ length: 10 }, (_, i) => String(new Date().getFullYear() - i));
const REPORT_TYPES = [
  { value: "sustainability", label: "Sustainability Report" },
  { value: "annual", label: "Annual Report (ESG section)" },
  { value: "csrd", label: "CSRD Disclosure" },
  { value: "gri", label: "GRI Standards Report" },
  { value: "tcfd", label: "TCFD Report" },
  { value: "other", label: "Other ESG Document" },
];

// ─── Make.com webhook URL — live VeriGreen ESG pipeline ───────────────────────
const MAKE_WEBHOOK_URL = import.meta.env.VITE_MAKE_WEBHOOK_URL ||
  "https://hook.eu1.make.com/wjrgqmyidyzporevwtmbpm5x4f15thr4";

// ─── Component ────────────────────────────────────────────────────────────────

export default function Home() {
  const [form, setForm] = useState<FormData>({
    companyName: "",
    reportingYear: String(new Date().getFullYear() - 1),
    reportType: "sustainability",
    file: null,
  });
  const [formState, setFormState] = useState<FormState>("idle");
  const [dragOver, setDragOver] = useState(false);
  const [activeStage, setActiveStage] = useState<number>(0);
  const [jobId, setJobId] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [claimCount, setClaimCount] = useState<number>(0);
  const [completionPct, setCompletionPct] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const stageIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Calculate form completion percentage
  useEffect(() => {
    let filled = 0;
    if (form.companyName.trim()) filled++;
    if (form.reportingYear) filled++;
    if (form.reportType) filled++;
    if (form.file) filled++;
    setCompletionPct(Math.round((filled / 4) * 100));
  }, [form]);

  // Animate pipeline stages during submission
  useEffect(() => {
    if (formState === "parsing") {
      // Stages 1-2: document ingest + parse
      setActiveStage(1);
      let stage = 1;
      stageIntervalRef.current = setInterval(() => {
        stage++;
        if (stage <= 2) {
          setActiveStage(stage);
        } else {
          if (stageIntervalRef.current) clearInterval(stageIntervalRef.current);
        }
      }, 800);
    } else if (formState === "submitting") {
      // Stages 3-7: Gemini, iterate, score, embed, persist
      setActiveStage(3);
      let stage = 3;
      stageIntervalRef.current = setInterval(() => {
        stage++;
        if (stage <= 7) {
          setActiveStage(stage);
        } else {
          if (stageIntervalRef.current) clearInterval(stageIntervalRef.current);
        }
      }, 700);
    } else if (formState === "success") {
      setActiveStage(8);
      if (stageIntervalRef.current) clearInterval(stageIntervalRef.current);
    } else if (formState === "idle" || formState === "ready") {
      setActiveStage(0);
      if (stageIntervalRef.current) clearInterval(stageIntervalRef.current);
    }
    return () => {
      if (stageIntervalRef.current) clearInterval(stageIntervalRef.current);
    };
  }, [formState]);

  const isReady = form.companyName.trim() && form.reportingYear && form.reportType && form.file;

  // ─── File handling ─────────────────────────────────────────────────────────

  const handleFile = useCallback((file: File) => {
    const allowed = ["application/pdf", "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "image/png", "image/jpeg", "image/webp"];
    if (!allowed.includes(file.type)) {
      toast.error("Unsupported file type. Please upload a PDF, Word document, or image.");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast.error("File too large. Maximum size is 50 MB.");
      return;
    }
    setForm(f => ({ ...f, file }));
    setFormState("ready");
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const removeFile = () => {
    setForm(f => ({ ...f, file: null }));
    setFormState("idle");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ─── Submission ────────────────────────────────────────────────────────────

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isReady || formState === "submitting") return;

    const id = nanoid(12);
    setJobId(id);
    setFormState("submitting");
    setErrorMsg("");

    try {
      // ── Step 1: Extract ESG claims from the document client-side ──
      setFormState("parsing");
      const parseResult = await parseEsgDocument(
        form.file!,
        form.companyName.trim(),
        form.reportingYear,
        id
      );

      if (parseResult.claims.length === 0) {
        throw new Error(
          `No ESG claims found in the document. Extracted ${parseResult.totalSentences} sentences ` +
          `but none matched ESG keywords. Try a different document or check that it contains sustainability content.`
        );
      }

      setClaimCount(parseResult.claims.length);
      setFormState("submitting");

      // ── Step 2: Send claims as JSON to Make.com v9 webhook ──
      const webhookPayload = {
        job_id: id,
        company_name: form.companyName.trim(),
        reporting_year: form.reportingYear,
        report_type: form.reportType,
        claim_count: parseResult.claims.length,
        extraction_method: parseResult.extractionMethod,
        claims: parseResult.claims,
      };

      const res = await fetch(MAKE_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(webhookPayload),
      });

      if (!res.ok) throw new Error(`Webhook returned ${res.status}`);

      setFormState("success");
      toast.success(
        `${parseResult.claims.length} ESG claims extracted and queued for validation.`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Submission failed";
      setErrorMsg(msg);
      setFormState("error");
      toast.error("Submission failed. Please try again.");
    }
  };

  const handleReset = () => {
    setForm({ companyName: "", reportingYear: String(new Date().getFullYear() - 1), reportType: "sustainability", file: null });
    setFormState("idle");
    setJobId("");
    setErrorMsg("");
    setActiveStage(0);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ─── Render ────────────────────────────────────────────────────────────────

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
              <span className="text-muted-foreground text-xs ml-2 hidden sm:inline">ESG Validation Portal</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground mono hidden md:block">
              Powered by Gemini 2.5 Flash · Mistral Embed-2312 · Supabase
            </span>
            <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
            <span className="text-xs text-primary font-medium">Live</span>
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <main className="flex-1 container py-8 lg:py-12">
        <div className="grid lg:grid-cols-[1fr_420px] gap-8 lg:gap-12 items-start">

          {/* ── Left: Pipeline visualization ── */}
          <div className="order-2 lg:order-1">
            {/* Hero text */}
            <div className="mb-8">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
              >
                <p className="text-primary text-xs font-semibold tracking-widest uppercase mb-3 mono">
                  AI-Powered ESG Audit
                </p>
                <h1 className="text-3xl lg:text-4xl font-bold leading-tight mb-4"
                  style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                  Submit your ESG report<br />
                  <span style={{ color: "oklch(0.82 0.22 150)" }}>for AI-powered audit.</span>
                </h1>
                <p className="text-muted-foreground text-base leading-relaxed max-w-lg">
                  Upload any sustainability report, CSRD disclosure, or ESG document.
                  The pipeline extracts every claim, scores it against 5 substantiation
                  indicators, generates semantic embeddings, and persists results to your
                  audit database — in under 30 seconds.
                </p>
              </motion.div>
            </div>

            {/* Pipeline diagram */}
            <div className="rounded-xl border border-border/50 p-6"
              style={{ background: "oklch(0.15 0.008 240)" }}>
              <p className="text-xs text-muted-foreground uppercase tracking-widest mono mb-5">
                8-Stage Native Make.com Pipeline
              </p>
              <div className="space-y-2">
                {PIPELINE_STAGES.map((stage, idx) => {
                  const isActive = activeStage === stage.id;
                  const isDone = activeStage > stage.id || formState === "success";
                  const Icon = stage.icon;
                  return (
                    <motion.div
                      key={stage.id}
                      className="flex items-center gap-3 p-3 rounded-lg pipeline-node"
                      style={{
                        background: isActive
                          ? "oklch(0.82 0.22 150 / 0.08)"
                          : isDone
                          ? "oklch(0.82 0.22 150 / 0.04)"
                          : "transparent",
                        borderLeft: isActive
                          ? "2px solid oklch(0.82 0.22 150)"
                          : isDone
                          ? "2px solid oklch(0.82 0.22 150 / 0.4)"
                          : "2px solid transparent",
                      }}
                      animate={isActive ? { x: [0, 2, 0] } : {}}
                      transition={{ duration: 0.3 }}
                    >
                      <div className={`w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 ${
                        isActive ? "emerald-glow" : ""
                      }`} style={{
                        background: isActive
                          ? "oklch(0.82 0.22 150)"
                          : isDone
                          ? "oklch(0.82 0.22 150 / 0.2)"
                          : "oklch(1 0 0 / 0.05)",
                      }}>
                        {isDone && !isActive ? (
                          <CheckCircle2 className="w-4 h-4" style={{ color: "oklch(0.82 0.22 150)" }} />
                        ) : (
                          <Icon className={`w-4 h-4 ${isActive ? "text-background" : "text-muted-foreground"}`} />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-semibold ${isActive ? "text-primary" : isDone ? "text-foreground/80" : "text-muted-foreground"}`}
                            style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                            {stage.label}
                          </span>
                          {isActive && (
                            <span className="text-xs px-1.5 py-0.5 rounded mono"
                              style={{ background: "oklch(0.82 0.22 150 / 0.15)", color: "oklch(0.82 0.22 150)" }}>
                              processing
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mono">{stage.desc}</p>
                      </div>
                      <span className="text-xs text-muted-foreground mono opacity-40">
                        {String(idx + 1).padStart(2, "0")}
                      </span>
                    </motion.div>
                  );
                })}
              </div>

              {/* Stats row */}
              <div className="mt-5 pt-4 border-t border-border/30 grid grid-cols-3 gap-4">
                {[
                  { label: "Avg. Claims", value: "15–40" },
                  { label: "Cost / Doc", value: "~$0.007" },
                  { label: "Latency", value: "< 30s" },
                ].map(s => (
                  <div key={s.label} className="text-center">
                    <p className="text-lg font-bold" style={{ fontFamily: "'Space Grotesk', sans-serif", color: "oklch(0.82 0.22 150)" }}>
                      {s.value}
                    </p>
                    <p className="text-xs text-muted-foreground">{s.label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Right: Upload Form ── */}
          <div className="order-1 lg:order-2">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="rounded-xl border border-border/50 overflow-hidden"
              style={{ background: "oklch(0.15 0.008 240)" }}
            >
              {/* Form header with progress */}
              <div className="px-6 pt-6 pb-4 border-b border-border/30">
                <h2 className="font-bold text-lg mb-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                  Upload ESG Report
                </h2>
                <p className="text-xs text-muted-foreground mb-3">
                  PDF, Word, or image — up to 50 MB
                </p>
                {/* Progress bar */}
                <div className="h-1 rounded-full overflow-hidden" style={{ background: "oklch(1 0 0 / 0.08)" }}>
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: "oklch(0.82 0.22 150)" }}
                    animate={{ width: `${completionPct}%` }}
                    transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1">{completionPct}% complete</p>
              </div>

              <AnimatePresence mode="wait">
                {formState === "success" ? (
                  <motion.div
                    key="success"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="p-6 text-center"
                  >
                    <div className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 emerald-glow"
                      style={{ background: "oklch(0.82 0.22 150 / 0.15)" }}>
                      <CheckCircle2 className="w-8 h-8" style={{ color: "oklch(0.82 0.22 150)" }} />
                    </div>
                    <h3 className="font-bold text-xl mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                      Validation Queued
                    </h3>
                    <p className="text-muted-foreground text-sm mb-4">
                      {claimCount > 0
                        ? `${claimCount} ESG claim${claimCount !== 1 ? 's' : ''} extracted and queued through the 6-stage Make.com pipeline.`
                        : "Your ESG report is being processed through the pipeline."}
                    </p>
                    <div className="rounded-lg p-3 mb-5 text-left" style={{ background: "oklch(1 0 0 / 0.04)" }}>
                      <p className="text-xs text-muted-foreground mb-1">Job ID</p>
                      <p className="mono text-sm font-medium" style={{ color: "oklch(0.82 0.22 150)" }}>{jobId}</p>
                      {claimCount > 0 && (
                        <>
                          <p className="text-xs text-muted-foreground mt-2 mb-1">Claims Queued</p>
                          <p className="mono text-sm font-medium" style={{ color: "oklch(0.82 0.22 150)" }}>{claimCount} claim{claimCount !== 1 ? 's' : ''}</p>
                        </>
                      )}
                      <p className="text-xs text-muted-foreground mt-2 mb-1">Document</p>
                      <p className="text-sm truncate">{form.file?.name}</p>
                    </div>
                    <Button onClick={handleReset} variant="outline" className="w-full">
                      Submit Another Report
                    </Button>
                  </motion.div>
                ) : (
                  <motion.form
                    key="form"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    onSubmit={handleSubmit}
                    className="p-6 space-y-5"
                  >
                    {/* Company Name */}
                    <div className="space-y-1.5">
                      <Label htmlFor="companyName" className="text-sm font-medium">
                        Company Name <span style={{ color: "oklch(0.82 0.22 150)" }}>*</span>
                      </Label>
                      <Input
                        id="companyName"
                        placeholder="e.g. Tata Consultancy Services"
                        value={form.companyName}
                        onChange={e => setForm(f => ({ ...f, companyName: e.target.value }))}
                        disabled={formState === "submitting"}
                        className="bg-input/50 border-border/50 focus:border-primary"
                      />
                    </div>

                    {/* Reporting Year + Report Type */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label className="text-sm font-medium">
                          Reporting Year <span style={{ color: "oklch(0.82 0.22 150)" }}>*</span>
                        </Label>
                        <Select
                          value={form.reportingYear}
                          onValueChange={v => setForm(f => ({ ...f, reportingYear: v }))}
                          disabled={formState === "submitting"}
                        >
                          <SelectTrigger className="bg-input/50 border-border/50">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {YEARS.map(y => (
                              <SelectItem key={y} value={y}>{y}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-sm font-medium">
                          Report Type <span style={{ color: "oklch(0.82 0.22 150)" }}>*</span>
                        </Label>
                        <Select
                          value={form.reportType}
                          onValueChange={v => setForm(f => ({ ...f, reportType: v }))}
                          disabled={formState === "submitting"}
                        >
                          <SelectTrigger className="bg-input/50 border-border/50">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {REPORT_TYPES.map(rt => (
                              <SelectItem key={rt.value} value={rt.value}>{rt.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {/* File Upload */}
                    <div className="space-y-1.5">
                      <Label className="text-sm font-medium">
                        ESG Document <span style={{ color: "oklch(0.82 0.22 150)" }}>*</span>
                      </Label>
                      {form.file ? (
                        <motion.div
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          className="flex items-center gap-3 p-3 rounded-lg border border-primary/30"
                          style={{ background: "oklch(0.82 0.22 150 / 0.06)" }}
                        >
                          <div className="w-8 h-8 rounded flex items-center justify-center flex-shrink-0"
                            style={{ background: "oklch(0.82 0.22 150 / 0.15)" }}>
                            <FileText className="w-4 h-4" style={{ color: "oklch(0.82 0.22 150)" }} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{form.file.name}</p>
                            <p className="text-xs text-muted-foreground mono">
                              {(form.file.size / 1024 / 1024).toFixed(2)} MB
                            </p>
                          </div>
                          {formState !== "submitting" && (
                            <button type="button" onClick={removeFile}
                              className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded">
                              <X className="w-4 h-4" />
                            </button>
                          )}
                        </motion.div>
                      ) : (
                        <div
                          className={`drop-zone rounded-lg p-6 text-center cursor-pointer ${dragOver ? "drag-over" : ""}`}
                          style={{ background: "oklch(1 0 0 / 0.03)" }}
                          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                          onDragLeave={() => setDragOver(false)}
                          onDrop={handleDrop}
                          onClick={() => fileInputRef.current?.click()}
                        >
                          <div className="w-10 h-10 rounded-lg flex items-center justify-center mx-auto mb-3"
                            style={{ background: "oklch(1 0 0 / 0.06)" }}>
                            <Upload className="w-5 h-5 text-muted-foreground" />
                          </div>
                          <p className="text-sm font-medium mb-1">Drop your document here</p>
                          <p className="text-xs text-muted-foreground">
                            or <span style={{ color: "oklch(0.82 0.22 150)" }}>browse files</span>
                          </p>
                          <p className="text-xs text-muted-foreground mt-2">PDF · Word · PNG · JPEG · up to 50 MB</p>
                        </div>
                      )}
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp"
                        className="hidden"
                        onChange={handleFileInput}
                      />
                    </div>

                    {/* Error */}
                    <AnimatePresence>
                      {formState === "error" && errorMsg && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          className="flex items-start gap-2 p-3 rounded-lg"
                          style={{ background: "oklch(0.65 0.22 25 / 0.1)", border: "1px solid oklch(0.65 0.22 25 / 0.3)" }}
                        >
                          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "oklch(0.65 0.22 25)" }} />
                          <p className="text-xs" style={{ color: "oklch(0.65 0.22 25)" }}>{errorMsg}</p>
                        </motion.div>
                      )}
                    </AnimatePresence>

                    {/* Submit */}
                    <Button
                      type="submit"
                      disabled={!isReady || formState === "submitting" || formState === "parsing"}
                      className="w-full font-semibold h-11 relative overflow-hidden"
                      style={{
                        background: isReady ? "oklch(0.82 0.22 150)" : "oklch(1 0 0 / 0.08)",
                        color: isReady ? "oklch(0.1 0.008 240)" : "oklch(0.5 0 0)",
                        fontFamily: "'Space Grotesk', sans-serif",
                      }}
                    >
                      {formState === "parsing" ? (
                        <span className="flex items-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Extracting Claims…
                        </span>
                      ) : formState === "submitting" ? (
                        <span className="flex items-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          {claimCount > 0 ? `Validating ${claimCount} Claims…` : "Running Validation…"}
                        </span>
                      ) : (
                        <span className="flex items-center gap-2">
                          Run Validation
                          <ChevronRight className="w-4 h-4" />
                        </span>
                      )}
                    </Button>

                    {/* Job ID preview */}
                    {jobId && (formState === "submitting" || formState === "parsing") && (
                      <motion.p
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-center text-xs text-muted-foreground mono"
                      >
                        Job ID: <span style={{ color: "oklch(0.82 0.22 150)" }}>{jobId}</span>
                      </motion.p>
                    )}

                    <p className="text-xs text-muted-foreground text-center">
                      Results are persisted to the audit database. No data is shared externally.
                    </p>
                  </motion.form>
                )}
              </AnimatePresence>
            </motion.div>
          </div>
        </div>
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-border/30 py-4">
        <div className="container flex items-center justify-between">
          <p className="text-xs text-muted-foreground mono">
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
