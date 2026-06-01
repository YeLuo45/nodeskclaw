<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  open: boolean
  fileName: string
  existingSize?: number
  existingDate?: string
  newSize?: number
}>()

const emit = defineEmits<{
  (e: 'resolve', strategy: 'keep_both' | 'overwrite' | 'cancel'): void
}>()

const { t } = useI18n()
const confirmingOverwrite = ref(false)

function formatSize(bytes?: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

function handleKeepBoth() {
  emit('resolve', 'keep_both')
}

function handleOverwrite() {
  if (!confirmingOverwrite.value) {
    confirmingOverwrite.value = true
    return
  }
  emit('resolve', 'overwrite')
  confirmingOverwrite.value = false
}

function handleCancel() {
  confirmingOverwrite.value = false
  emit('resolve', 'cancel')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="handleCancel" />
      <div class="relative bg-background border border-border rounded-xl shadow-xl p-5 w-[380px] space-y-4">
        <div class="flex items-start gap-3">
          <div class="w-9 h-9 rounded-full bg-yellow-500/10 flex items-center justify-center shrink-0">
            <AlertTriangle class="w-5 h-5 text-yellow-600" />
          </div>
          <div class="space-y-1">
            <h3 class="text-sm font-semibold">{{ t('upload.conflict.title') }}</h3>
            <p class="text-xs text-muted-foreground">
              {{ t('upload.conflict.description', { name: fileName }) }}
            </p>
          </div>
        </div>

        <div class="space-y-1 text-xs text-muted-foreground pl-12">
          <p v-if="existingSize || existingDate">
            {{ t('upload.conflict.existingFile', { size: formatSize(existingSize), date: existingDate || '-' }) }}
          </p>
          <p v-if="newSize">
            {{ t('upload.conflict.newFile', { size: formatSize(newSize) }) }}
          </p>
        </div>

        <p v-if="confirmingOverwrite" class="text-xs text-destructive pl-12">
          {{ t('upload.conflict.confirmOverwrite') }}
        </p>

        <div class="flex items-center justify-end gap-2 pt-1">
          <Button variant="unstyled" size="unstyled"
            class="h-8 px-3 text-xs rounded-md border border-input hover:bg-muted transition-colors"
            @click="handleCancel"
          >
            {{ t('upload.actions.cancel') }}
          </Button>
          <Button variant="unstyled" size="unstyled"
            class="h-8 px-3 text-xs rounded-md border border-input hover:bg-muted transition-colors"
            @click="handleKeepBoth"
          >
            {{ t('upload.actions.keep_both') }}
          </Button>
          <Button variant="unstyled" size="unstyled"
            class="h-8 px-3 text-xs rounded-md text-destructive-foreground transition-colors"
            :class="confirmingOverwrite ? 'bg-destructive hover:bg-destructive/90' : 'bg-destructive/80 hover:bg-destructive'"
            @click="handleOverwrite"
          >
            {{ t('upload.actions.overwrite') }}
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
