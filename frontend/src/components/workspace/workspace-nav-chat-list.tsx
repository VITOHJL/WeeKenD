"use client";

import { BotIcon, MessagesSquare, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

import { PersonalityTestDialog } from "./personality/personality-test-dialog";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const [testOpen, setTestOpen] = useState(false);
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/agents")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/agents">
              <BotIcon />
              <span>{t.sidebar.agents}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            className="text-muted-foreground"
            onClick={() => setTestOpen(true)}
          >
            <SparklesIcon />
            <span>{t.sidebar.personalityTest}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <PersonalityTestDialog open={testOpen} onOpenChange={setTestOpen} />
    </SidebarGroup>
  );
}
