"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useMemory,
} from "@/core/memory/hooks";

import {
  DIM_LABELS,
  PERSONAS,
  QUESTIONS,
  computeCode,
  dimPercent,
  emptyScores,
  resolvePersona,
  type Persona,
  type Scores,
} from "./quiz-data";

export const PERSONALITY_CATEGORY = "personality";

type Phase = "start" | "quiz" | "result";

export function PersonalityTestDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [phase, setPhase] = useState<Phase>("start");
  const [qIdx, setQIdx] = useState(0);
  const [scores, setScores] = useState<Scores>(emptyScores());
  const [persona, setPersona] = useState<Persona | null>(null);
  const [code, setCode] = useState("");
  const [saving, setSaving] = useState(false);

  const { memory } = useMemory();
  const createFact = useCreateMemoryFact();
  const deleteFact = useDeleteMemoryFact();

  function reset() {
    setPhase("start");
    setQIdx(0);
    setScores(emptyScores());
    setPersona(null);
    setCode("");
  }

  function start() {
    setScores(emptyScores());
    setQIdx(0);
    setPhase("quiz");
  }

  function pick(optIdx: number) {
    const opt = QUESTIONS[qIdx]!.options[optIdx]!;
    const next = { ...scores };
    for (const [k, v] of Object.entries(opt.scores)) {
      next[k as keyof Scores] = (next[k as keyof Scores] || 0) + (v ?? 0);
    }
    setScores(next);
    toast(opt.feedback, { duration: 1500 });

    if (qIdx + 1 >= QUESTIONS.length) {
      finish(next);
    } else {
      setQIdx(qIdx + 1);
    }
  }

  function finish(finalScores: Scores) {
    const c = computeCode(finalScores);
    const { persona: p } = resolvePersona(c);
    setCode(c);
    setPersona(p);
    setPhase("result");
  }

  async function saveToMemory() {
    if (!persona) return;
    setSaving(true);
    try {
      // 先删掉旧的人格记忆，避免堆叠矛盾
      const old = (memory?.facts ?? []).filter(
        (f) => f.category === PERSONALITY_CATEGORY,
      );
      for (const f of old) {
        await deleteFact.mutateAsync(f.id);
      }

      const dimText = DIM_LABELS.map((d) => {
        const pct = dimPercent(scores, d.lp, d.rp);
        return pct >= 50 ? `${d.left}${pct}%` : `${d.right}${100 - pct}%`;
      }).join("、");

      await createFact.mutateAsync({
        content: `用户的周末旅行人格是「${persona.name}」（${code}）。特点：${persona.traits.join("、")}。一句话：${persona.tagline}`,
        category: PERSONALITY_CATEGORY,
        confidence: 0.9,
      });
      await createFact.mutateAsync({
        content: `用户的周末出行五维画像：${dimText}。规划时请据此调整风格（如独处型勿强推组队、性价比型控预算、计划控给明确时间表）。`,
        category: PERSONALITY_CATEGORY,
        confidence: 0.9,
      });

      toast.success("已记住你的周末人格，之后规划会更懂你 ✨");
      onOpenChange(false);
      reset();
    } catch {
      toast.error("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  const q = QUESTIONS[qIdx];

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) reset();
      }}
    >
      <DialogContent className="max-w-md overflow-hidden p-0">
        <div
          className="max-h-[80vh] overflow-y-auto px-6 py-6"
          style={{ background: "#faf6f0", color: "#2c2416" }}
        >
          {/* ─── START ─── */}
          {phase === "start" && (
            <div className="flex flex-col items-center py-6 text-center">
              <div
                className="mb-5 flex h-20 w-20 items-center justify-center rounded-full text-4xl shadow-lg"
                style={{ background: "linear-gradient(135deg,#e85d3a,#f0c040)" }}
              >
                🧳
              </div>
              <DialogHeader>
                <DialogTitle className="text-center text-2xl font-black">
                  你的周末，到底是怎么
                  <span style={{ color: "#e85d3a" }}>没的</span>
                </DialogTitle>
              </DialogHeader>
              <p className="mt-2 mb-6 text-sm" style={{ color: "#8a7e6b" }}>
                8道题 · 场景代入 · 测出你的「周末旅行人格」
                <br />
                结果会被记住，之后规划周末更懂你
              </p>
              <Button
                onClick={start}
                className="rounded-full px-10 py-6 text-base font-bold"
                style={{ background: "#2c2416", color: "#faf6f0" }}
              >
                开始测试 →
              </Button>
            </div>
          )}

          {/* ─── QUIZ ─── */}
          {phase === "quiz" && q && (
            <div>
              <div className="mb-4 flex items-center gap-3">
                <span className="font-mono text-xs" style={{ color: "#8a7e6b" }}>
                  {qIdx + 1} / {QUESTIONS.length}
                </span>
                <div
                  className="h-[3px] flex-1 overflow-hidden rounded"
                  style={{ background: "rgba(44,36,22,0.08)" }}
                >
                  <div
                    className="h-full rounded transition-all duration-500"
                    style={{
                      width: `${(qIdx / QUESTIONS.length) * 100}%`,
                      background: "#e85d3a",
                    }}
                  />
                </div>
                <span
                  className="rounded-full px-2 py-0.5 font-mono text-[10px] uppercase"
                  style={{
                    background:
                      q.type === "scoring"
                        ? "rgba(232,93,58,0.1)"
                        : "rgba(58,140,232,0.1)",
                    color: q.type === "scoring" ? "#e85d3a" : "#3a8ce8",
                  }}
                >
                  {q.type === "scoring" ? "计分题" : "彩蛋题"}
                </span>
              </div>

              <div
                className="mb-4 rounded-2xl border p-6"
                style={{
                  background: "#fff",
                  borderColor: "rgba(44,36,22,0.06)",
                }}
              >
                <div className="mb-3 text-center text-5xl">{q.illustration}</div>
                <div className="mb-1 text-center text-base font-semibold leading-relaxed">
                  {q.scene}
                </div>
                <div
                  className="mb-5 text-center text-xs italic"
                  style={{ color: "#8a7e6b" }}
                >
                  {q.mood}
                </div>
                <div className="flex flex-col gap-2.5">
                  {q.options.map((opt, i) => (
                    <button
                      key={opt.label}
                      onClick={() => pick(i)}
                      className="rounded-lg border p-4 text-left text-sm transition-all hover:translate-x-1"
                      style={{ borderColor: "rgba(44,36,22,0.1)" }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.borderColor = "#e85d3a")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.borderColor =
                          "rgba(44,36,22,0.1)")
                      }
                    >
                      <div
                        className="mb-1 font-mono text-[11px]"
                        style={{ color: "#8a7e6b" }}
                      >
                        选项 {opt.label}
                      </div>
                      <div className="font-medium">{opt.innerOS}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ─── RESULT ─── */}
          {phase === "result" && persona && (
            <div>
              <div className="py-2 text-center">
                <div className="mb-3 text-6xl">{persona.emoji}</div>
                <div
                  className="mb-2 inline-block rounded px-3 py-1 font-mono text-xs"
                  style={{ background: "#f0ebe0", color: "#8a7e6b" }}
                >
                  {code}
                </div>
                <div className="mb-1 text-2xl font-black">{persona.name}</div>
                <div
                  className="mx-auto mb-4 max-w-xs text-sm italic"
                  style={{ color: "#8a7e6b" }}
                >
                  {persona.tagline}
                </div>
              </div>

              {/* 五维画像 */}
              <div
                className="mb-4 rounded-2xl border p-5"
                style={{ background: "#fff", borderColor: "rgba(44,36,22,0.06)" }}
              >
                <h3 className="mb-4 text-sm font-bold">📊 五维画像</h3>
                {DIM_LABELS.map((d) => {
                  const pct = dimPercent(scores, d.lp, d.rp);
                  return (
                    <div key={d.lp} className="mb-3 flex items-center gap-2">
                      <span
                        className="w-14 text-right text-xs"
                        style={{ color: "#8a7e6b" }}
                      >
                        {d.left}
                      </span>
                      <div
                        className="relative h-2 flex-1 overflow-hidden rounded"
                        style={{ background: "rgba(44,36,22,0.06)" }}
                      >
                        <div
                          className="absolute left-0 top-0 h-full rounded transition-all duration-700"
                          style={{ width: `${pct}%`, background: "#e85d3a" }}
                        />
                      </div>
                      <span
                        className="w-14 text-left text-xs"
                        style={{ color: "#8a7e6b" }}
                      >
                        {d.right}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* 档案 */}
              <div
                className="mb-4 rounded-2xl border p-5"
                style={{ background: "#fff", borderColor: "rgba(44,36,22,0.06)" }}
              >
                <h3 className="mb-3 text-sm font-bold">📋 人格档案</h3>
                <p className="mb-3 text-sm leading-relaxed">{persona.desc}</p>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {persona.traits.map((t) => (
                    <span
                      key={t}
                      className="rounded-full px-3 py-1 text-[11px]"
                      style={{ background: "#f0ebe0", color: "#8a7e6b" }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
                <div
                  className="rounded-lg p-3 text-xs leading-relaxed"
                  style={{ background: "rgba(232,93,58,0.05)", color: "#e85d3a" }}
                >
                  <strong style={{ color: "#2c2416" }}>⚠️ 最怕遇到：</strong>
                  {persona.nightmare}
                </div>
              </div>

              <div className="flex gap-2">
                <Button
                  onClick={saveToMemory}
                  disabled={saving}
                  className="flex-1 rounded-full py-5 font-bold"
                  style={{ background: "#2c2416", color: "#faf6f0" }}
                >
                  {saving ? "保存中…" : "✨ 记住我的人格"}
                </Button>
                <Button
                  onClick={start}
                  variant="secondary"
                  className="rounded-full py-5"
                >
                  🔄 重测
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
