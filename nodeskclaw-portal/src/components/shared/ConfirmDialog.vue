<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirmState } from '@/composables/useConfirm'
import { TriangleAlert } from 'lucide-vue-next'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

const { t } = useI18n()
const { state, handleConfirm, handleCancel } = useConfirmState()
const pendingAction = ref<'confirm' | 'cancel' | null>(null)

function onOpenChange(open: boolean) {
  if (open || !state.value.visible) return
  const action = pendingAction.value
  pendingAction.value = null
  if (action === 'confirm') {
    handleConfirm()
  } else {
    handleCancel()
  }
}

function markConfirm() {
  pendingAction.value = 'confirm'
}

function markCancel() {
  pendingAction.value = 'cancel'
}

function confirmNow() {
  pendingAction.value = null
  handleConfirm()
}

function cancelNow() {
  pendingAction.value = null
  handleCancel()
}
</script>

<template>
  <AlertDialog :open="state.visible" @update:open="onOpenChange">
    <AlertDialogContent class="max-w-sm border-border bg-popover">
      <AlertDialogHeader>
        <AlertDialogTitle v-if="state.title" class="flex items-center gap-2">
          <TriangleAlert
            v-if="state.variant === 'danger'"
            class="h-5 w-5 shrink-0 text-destructive"
          />
          {{ state.title }}
        </AlertDialogTitle>
        <AlertDialogDescription class="leading-relaxed">
          {{ state.description }}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel
          v-if="!state.isAlert"
          @pointerdown.capture="markCancel"
          @keydown.enter.capture="markCancel"
          @keydown.space.capture="markCancel"
          @click="cancelNow"
        >
          {{ state.cancelText || t('common.cancel') }}
        </AlertDialogCancel>
        <AlertDialogAction
          :class="state.variant === 'danger' ? 'bg-destructive text-white hover:bg-destructive/90' : ''"
          @pointerdown.capture="markConfirm"
          @keydown.enter.capture="markConfirm"
          @keydown.space.capture="markConfirm"
          @click="confirmNow"
        >
          {{ state.confirmText || t('common.confirm') }}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
