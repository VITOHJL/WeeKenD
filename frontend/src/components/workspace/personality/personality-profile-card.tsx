"use client";

import { SparklesIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { useMemory } from "@/core/memory/hooks";

import { PERSONALITY_CATEGORY, PersonalityTestDialog } from "./personality-test-dialog";
import { PERSONAS } from "./quiz-data";

// 从记忆里粗略解析出已测过的人格名 + emoji（demo 用正则）
function useCurrentPersona() {
  const { memory } = useMemory();
  return useMemo(() => {
    const fact = (memory?.facts ?? []).find(
      (f) =>
        f.category === PERSONALITY_CATEGORY && f.content.includes("人格是「"),
    );
    if (!fact) return null;
    const m = /人格是「(.+?)」/.exec(fact.content);
    const name = m?.[1];
    if (!name) return null;
    const emoji =
      Object.values(PERSONAS).find((p) => p.name === name)?.emoji ?? "🧭";
    return { name, emoji };
  }, [memory]);
}

export function PersonalityProfileCard() {
  const [open, setOpen] = useState(false);
  const { open: sidebarOpen } = useSidebar();
  const current = useCurrentPersona();

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={current ? `周末人格：${current.name}（点击重测）` : "测一测你的周末旅行人格"}
        className="mx-2 mb-1 flex items-center gap-2 rounded-lg border border-border/60 bg-sidebar-accent/40 px-2.5 py-2 text-left text-sm transition-colors hover:bg-sidebar-accent"
      >
        <span className="text-lg leading-none">
          {current ? current.emoji : <SparklesIcon className="size-4" />}
        </span>
        {sidebarOpen && (
          <span className="min-w-0 flex-1">
            {current ? (
              <>
                <span className="block truncate font-medium">{current.name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  我的周末人格 · 点击重测
                </span>
              </>
            ) : (
              <span className="block text-muted-foreground">
                测一测周末人格 →
              </span>
            )}
          </span>
        )}
      </button>
      <PersonalityTestDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
