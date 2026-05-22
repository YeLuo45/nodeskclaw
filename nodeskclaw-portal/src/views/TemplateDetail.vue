<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  Loader2,
  Package,
  Code,
  Database,
  Cpu,
  Server,
  Shield,
  Zap,
  Wrench,
  Palette,
  MessageSquare,
  Network,
  Sparkles,
  Layers,
  Download,
  Dna,
  Pencil,
  Trash2,
  Upload,
  KeyRound,
  FileText,
  Check,
  X,
} from 'lucide-vue-next'
import { useGeneStore } from '@/stores/gene'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const route = useRoute()
const router = useRouter()
const store = useGeneStore()
const toast = useToast()
const { confirm } = useConfirm()
const { t } = useI18n()

const templateId = computed(() => route.params.id as string)
const tpl = computed(() => store.currentTemplate)
const deleting = ref(false)
const editingName = ref(false)
const editingNameValue = ref('')
const savingName = ref(false)
const bundleSkills = computed(() => tpl.value?.agent_bundle?.skills ?? [])
const bundleFiles = computed(() => tpl.value?.agent_bundle?.files ?? [])
const bundleEnvKeys = computed(() => tpl.value?.agent_bundle?.env_keys ?? [])
const resourceEntries = computed(() => Object.entries(tpl.value?.resource_recommendation ?? {}))
const uploadEntries = computed(() => Object.entries(tpl.value?.upload_contract ?? {}))

const iconMap: Record<string, typeof Package> = {
  code: Code,
  database: Database,
  cpu: Cpu,
  server: Server,
  shield: Shield,
  zap: Zap,
  wrench: Wrench,
  palette: Palette,
  message: MessageSquare,
  network: Network,
  sparkles: Sparkles,
  layers: Layers,
  package: Package,
}

function resolveIcon(iconName?: string) {
  if (!iconName) return Package
  const key = iconName.toLowerCase().replace(/[- ]/g, '')
  return iconMap[key] ?? iconMap[iconName] ?? Package
}

onMounted(() => {
  store.fetchTemplate(templateId.value)
})

function useThisTemplate() {
  router.push({ name: 'CreateInstance', query: { template_id: templateId.value } })
}

function startNameEdit() {
  if (!tpl.value) return
  editingName.value = true
  editingNameValue.value = tpl.value.name
}

function cancelNameEdit() {
  editingName.value = false
  editingNameValue.value = ''
}

async function saveNameEdit() {
  if (!tpl.value) return
  const nextName = editingNameValue.value.trim()
  if (!nextName) {
    toast.error(t('template.displayNameRequired'))
    return
  }
  savingName.value = true
  try {
    await store.updateTemplate(tpl.value.id, { name: nextName })
    toast.success(t('template.displayNameUpdated'))
    cancelNameEdit()
  } catch (e: any) {
    toast.error(e?.response?.data?.message || t('template.displayNameUpdateFailed'))
  } finally {
    savingName.value = false
  }
}

async function handleDelete() {
  const ok = await confirm({
    description: t('template.deleteConfirm'),
    variant: 'danger',
  })
  if (!ok) return
  deleting.value = true
  try {
    await store.deleteTemplate(templateId.value)
    toast.success(t('template.deleted'))
    router.push({ path: '/gene-market', query: { tab: 'templates' } })
  } catch {
    toast.error(t('template.deleteFailed'))
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)] bg-background text-foreground">
    <div class="shrink-0 border-b border-border">
      <div class="max-w-4xl mx-auto px-6 py-4">
        <Button variant="unstyled" size="unstyled"
          class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
          @click="router.push('/gene-market')"
        >
          <ArrowLeft class="w-4 h-4" />
          {{ t('template.backToMarket') }}
        </Button>
      </div>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="max-w-4xl mx-auto px-6 py-6">
        <div v-if="store.loading" class="flex justify-center py-20">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>

        <template v-else-if="tpl">
          <div class="flex items-start gap-4 mb-8">
            <div class="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
              <component :is="resolveIcon(tpl.icon)" class="w-7 h-7 text-primary" />
            </div>
            <div class="flex-1 min-w-0">
              <div v-if="editingName" class="flex items-center gap-2 mb-2">
                <Input
                  v-model="editingNameValue"
                  class="h-10 max-w-md text-lg font-semibold"
                  :placeholder="t('template.displayNamePlaceholder')"
                  @keydown.enter.stop.prevent="saveNameEdit"
                  @keydown.esc.stop.prevent="cancelNameEdit"
                />
                <Button variant="unstyled" size="unstyled"
                  class="p-2 rounded-lg text-primary hover:bg-primary/10 disabled:opacity-50"
                  :title="t('template.saveDisplayName')"
                  :aria-label="t('template.saveDisplayName')"
                  :disabled="savingName"
                  @click="saveNameEdit"
                >
                  <Loader2 v-if="savingName" class="w-4 h-4 animate-spin" />
                  <Check v-else class="w-4 h-4" />
                </Button>
                <Button variant="unstyled" size="unstyled"
                  class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
                  :title="t('common.cancel')"
                  :aria-label="t('common.cancel')"
                  @click="cancelNameEdit"
                >
                  <X class="w-4 h-4" />
                </Button>
              </div>
              <div v-else class="flex items-center gap-2 mb-1">
                <h1 class="text-2xl font-bold truncate">{{ tpl.name }}</h1>
                <Button variant="unstyled" size="unstyled"
                  v-if="tpl.template_type === 'agent_bundle'"
                  class="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
                  :title="t('template.editDisplayName')"
                  :aria-label="t('template.editDisplayName')"
                  @click="startNameEdit"
                >
                  <Pencil class="w-4 h-4" />
                </Button>
              </div>
              <p v-if="tpl.template_type === 'agent_bundle' && tpl.agent_bundle?.name" class="text-sm text-muted-foreground mb-1">
                {{ t('template.standardName') }}: {{ tpl.agent_bundle.name }}
              </p>
              <p v-if="tpl.short_description" class="text-muted-foreground">{{ tpl.short_description }}</p>
              <div class="flex items-center gap-4 mt-3 text-sm text-muted-foreground">
                <span class="flex items-center gap-1">
                  <Dna class="w-4 h-4" />
                  {{ t('template.geneCount', { count: tpl.gene_slugs?.length ?? 0 }) }}
                </span>
                <span class="flex items-center gap-1">
                  <Download class="w-4 h-4" />
                  {{ t('template.useCount', { count: tpl.use_count ?? 0 }) }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <Button variant="unstyled" size="unstyled"
                class="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                @click="useThisTemplate"
              >
                {{ t('template.useTemplate') }}
              </Button>
              <Button variant="unstyled" size="unstyled"
                class="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                :disabled="deleting"
                @click="handleDelete"
              >
                <Loader2 v-if="deleting" class="w-4 h-4 animate-spin" />
                <Trash2 v-else class="w-4 h-4" />
              </Button>
            </div>
          </div>

          <div v-if="tpl.description" class="mb-8">
            <h2 class="text-lg font-semibold mb-3">{{ t('template.description') }}</h2>
            <p class="text-muted-foreground whitespace-pre-wrap">{{ tpl.description }}</p>
          </div>

          <div v-if="tpl.template_type === 'agent_bundle'" class="mb-8 space-y-4">
            <div class="rounded-lg border border-border bg-card p-4">
              <div class="flex items-center gap-2 mb-3">
                <Package class="w-4 h-4 text-primary" />
                <h2 class="text-lg font-semibold">{{ t('template.agentBundleTitle') }}</h2>
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div class="rounded-md bg-muted/40 p-3">
                  <div class="text-xs text-muted-foreground">{{ t('template.bundleModel') }}</div>
                  <div class="font-medium truncate">{{ tpl.agent_bundle?.model || '-' }}</div>
                </div>
                <div class="rounded-md bg-muted/40 p-3">
                  <div class="text-xs text-muted-foreground">{{ t('template.bundleSkillCount') }}</div>
                  <div class="font-medium">{{ bundleSkills.length }}</div>
                </div>
                <div class="rounded-md bg-muted/40 p-3">
                  <div class="text-xs text-muted-foreground">{{ t('template.bundleFileCount') }}</div>
                  <div class="font-medium">{{ bundleFiles.length }}</div>
                </div>
                <div class="rounded-md bg-muted/40 p-3">
                  <div class="text-xs text-muted-foreground">{{ t('template.bundleEnvCount') }}</div>
                  <div class="font-medium">{{ bundleEnvKeys.length }}</div>
                </div>
              </div>

              <div v-if="bundleSkills.length" class="mt-4">
                <div class="text-sm font-medium mb-2">{{ t('template.bundleSkills') }}</div>
                <div class="space-y-2">
                  <div
                    v-for="skill in bundleSkills"
                    :key="skill.slug || skill.name"
                    class="flex items-center gap-3 rounded-md border border-border px-3 py-2"
                  >
                    <Wrench class="w-4 h-4 text-muted-foreground shrink-0" />
                    <div class="min-w-0 flex-1">
                      <div class="text-sm font-medium truncate">{{ skill.name }}</div>
                      <div class="text-xs text-muted-foreground truncate">{{ skill.description }}</div>
                    </div>
                    <span class="text-xs text-muted-foreground shrink-0">v{{ skill.version || '1.0.0' }}</span>
                  </div>
                </div>
              </div>

              <div v-if="bundleFiles.length" class="mt-4">
                <div class="text-sm font-medium mb-2">{{ t('template.bundleFiles') }}</div>
                <div class="flex flex-wrap gap-1.5">
                  <span
                    v-for="file in bundleFiles.slice(0, 12)"
                    :key="file"
                    class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground"
                  >
                    <FileText class="w-3 h-3" />
                    {{ file }}
                  </span>
                </div>
              </div>
            </div>

            <div v-if="resourceEntries.length || uploadEntries.length || (tpl.secret_refs?.length ?? 0) > 0" class="grid md:grid-cols-3 gap-3">
              <div v-if="resourceEntries.length" class="rounded-lg border border-border bg-card p-4">
                <div class="flex items-center gap-2 text-sm font-medium mb-3">
                  <Cpu class="w-4 h-4 text-blue-400" />
                  {{ t('template.resourceRecommendation') }}
                </div>
                <div class="space-y-1 text-xs">
                  <div v-for="[key, value] in resourceEntries" :key="key" class="flex justify-between gap-3">
                    <span class="text-muted-foreground">{{ key }}</span>
                    <span class="font-mono text-right">{{ value }}</span>
                  </div>
                </div>
              </div>

              <div v-if="uploadEntries.length" class="rounded-lg border border-border bg-card p-4">
                <div class="flex items-center gap-2 text-sm font-medium mb-3">
                  <Upload class="w-4 h-4 text-orange-400" />
                  {{ t('template.uploadContract') }}
                </div>
                <div class="space-y-1 text-xs">
                  <div v-for="[key, value] in uploadEntries" :key="key" class="flex justify-between gap-3">
                    <span class="text-muted-foreground">{{ key }}</span>
                    <span class="font-mono text-right truncate">{{ Array.isArray(value) ? value.join(', ') : value }}</span>
                  </div>
                </div>
              </div>

              <div v-if="(tpl.secret_refs?.length ?? 0) > 0" class="rounded-lg border border-border bg-card p-4">
                <div class="flex items-center gap-2 text-sm font-medium mb-3">
                  <KeyRound class="w-4 h-4 text-amber-400" />
                  {{ t('template.secretRefs') }}
                </div>
                <div class="space-y-1 text-xs">
                  <div
                    v-for="ref in tpl.secret_refs"
                    :key="`${ref.env || ref.env_name}-${ref.secretName || ref.secret_name}`"
                    class="flex justify-between gap-3"
                  >
                    <span class="text-muted-foreground">{{ ref.env || ref.env_name }}</span>
                    <span class="font-mono text-right">{{ ref.secretName || ref.secret_name || ref.tokenRef || ref.token_ref }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div>
            <h2 class="text-lg font-semibold mb-3">{{ t('template.includedGenes') }}</h2>
            <div v-if="!tpl.genes || tpl.genes.length === 0" class="text-muted-foreground text-sm py-8 text-center">
              {{ t('template.noGenes') }}
            </div>
            <div v-else class="space-y-2">
              <div
                v-for="gene in tpl.genes"
                :key="gene.slug"
                class="flex items-center gap-3 p-3 rounded-lg border border-border bg-card"
              >
                <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <component :is="resolveIcon(gene.icon)" class="w-4 h-4 text-primary" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="font-medium text-sm">{{ gene.name }}</div>
                  <div v-if="gene.short_description" class="text-xs text-muted-foreground line-clamp-1">{{ gene.short_description }}</div>
                </div>
                <span v-if="gene.category" class="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                  {{ gene.category }}
                </span>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="text-center py-20 text-muted-foreground">
          {{ t('template.notFound') }}
        </div>
      </div>
    </div>
  </div>
</template>
