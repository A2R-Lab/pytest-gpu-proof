from abc import ABC, abstractmethod


class SignerBase(ABC):
    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        ...

    @abstractmethod
    def key_fingerprint(self) -> str:
        ...


class VerifierError(Exception):
    pass
