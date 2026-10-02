'use client';

import { useEffect, useId, useRef } from 'react';

type ActionConfirmationDialogProps = {
  cancelLabel: string;
  confirmLabel: string;
  description: string;
  open: boolean;
  pending: boolean;
  title: string;
  onCancel: () => void;
  onConfirm: () => void;
};

export function ActionConfirmationDialog({
  cancelLabel,
  confirmLabel,
  description,
  open,
  pending,
  title,
  onCancel,
  onConfirm,
}: ActionConfirmationDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const onCancelRef = useRef(onCancel);
  const pendingRef = useRef(pending);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    onCancelRef.current = onCancel;
    pendingRef.current = pending;
  }, [onCancel, pending]);

  useEffect(() => {
    if (!open) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      if (!pendingRef.current) onCancelRef.current();
    };
    document.addEventListener('keydown', handleEscape, true);
    return () => document.removeEventListener('keydown', handleEscape, true);
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-busy={pending}
      className="action-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
      ref={dialogRef}
      role="alertdialog"
    >
      <div className="action-confirmation-content">
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        <div className="action-confirmation-actions">
          <button autoFocus className="button secondary" disabled={pending} onClick={onCancel} type="button">{cancelLabel}</button>
          <button className="button danger" disabled={pending} onClick={onConfirm} type="button">{confirmLabel}</button>
        </div>
      </div>
    </dialog>
  );
}
