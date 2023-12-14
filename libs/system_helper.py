import os


class Architecture:
    @staticmethod
    def is_arm() -> bool:
        return "ARM64" in os.uname().version

    @staticmethod
    def is_x86() -> bool:
        return "X86_64" in os.uname().version
