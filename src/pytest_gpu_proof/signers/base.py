from abc import ABC, abstractmethod


class SignerBase(ABC):
    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        ...

    @abstractmethod
    def key_fingerprint(self) -> str:
        ...

    @abstractmethod
    def algorithm(self) -> str:
        """Name of the signature algorithm actually used (e.g. 'ed25519')."""
        ...


class VerifierError(Exception):
    pass
