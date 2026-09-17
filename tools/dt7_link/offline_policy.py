"""Transport-only fixtures; never import this policy from application code.

These deliberately isolate framing/serial recovery from authorization. The
integration suite tests real OfficialSafety and authenticated evidence instead.
"""
class OfflineDt7Safety:
    def can_transmit_dt7(self, **kwargs):
        return True, "offline transport fixture"
    def mark_published(self, *args, **kwargs):
        pass
    def lock_control(self, reason):
        pass
