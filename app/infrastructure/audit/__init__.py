"""Pacote de auditoria — artefatos de evidência de cada execução (logs + screenshots)."""

from infrastructure.audit.audit_session import AuditSession, AUDIT_DIR

__all__ = ["AuditSession", "AUDIT_DIR"]
