import hashlib
import os
import struct
import unittest

from shirdal.mtproto import (
    AuthKey,
    HandshakeSession,
    MTProtoCryptoError,
    RSAPublicKey,
    TLReader,
    TLWriter,
    aes_ige_decrypt,
    aes_ige_encrypt,
    derive_tmp_aes_key_iv,
    factorize_pq,
)
from shirdal.mtproto.auth import (
    CLIENT_DH_INNER_DATA_ID,
    DH_GEN_OK_ID,
    P_Q_INNER_DATA_ID,
    REQ_DH_PARAMS_ID,
    REQ_PQ_MULTI_ID,
    RES_PQ_ID,
    SERVER_DH_INNER_DATA_ID,
    SERVER_DH_PARAMS_OK_ID,
    SET_CLIENT_DH_PARAMS_ID,
)


class TestPhase27MTProtoCryptoAuth(unittest.TestCase):
    def test_aes_256_ige_roundtrip_and_tamper_rejection(self) -> None:
        key = bytes(range(32))
        iv = bytes(range(32, 64))
        plaintext = b"Shirdal MTProto 2.0 IGE Test!!!!" * 2  # 64 bytes
        ciphertext = aes_ige_encrypt(plaintext, key, iv)
        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(aes_ige_decrypt(ciphertext, key, iv), plaintext)

        with self.assertRaises(MTProtoCryptoError):
            aes_ige_encrypt(b"not_16_aligned", key, iv)

    def test_auth_key_packet_encrypt_decrypt_and_integrity(self) -> None:
        auth_key = AuthKey(os.urandom(256))
        inner = b"\x01\x02\x03\x04" * 8
        wire = auth_key.encrypt_packet(inner, from_client=True)
        decrypted_padded = auth_key.decrypt_packet(wire, from_client=True)
        self.assertTrue(decrypted_padded.startswith(inner))
        self.assertGreaterEqual(len(decrypted_padded) - len(inner), 12)

        # Tampering 1 byte of ciphertext must fail msg_key verification
        bad_wire = bytearray(wire)
        bad_wire[-1] ^= 0xFF
        with self.assertRaises(MTProtoCryptoError):
            auth_key.decrypt_packet(bytes(bad_wire), from_client=True)

    def test_pollard_rho_factorization(self) -> None:
        p, q = 1_000_000_007, 1_000_000_009
        fp, fq = factorize_pq(p * q)
        self.assertEqual((fp, fq), (p, q))

    def test_full_diffie_hellman_handshake_simulation(self) -> None:
        # Generate a small valid RSA keypair (>= 2048 bits) and safe DH group for simulation
        p_rsa = (1 << 1023) + 1155
        q_rsa = (1 << 1023) + 1221
        # Use a deterministic 2048-bit modulus with e=65537 where we know d?
        # Simpler: use cryptography's RSA key generator so n, e, d are 100% mathematically valid!
        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_nums = priv.public_key().public_numbers()
        priv_nums = priv.private_numbers()
        rsa_key = RSAPublicKey(n=pub_nums.n, e=pub_nums.e)

        session = HandshakeSession([rsa_key])
        req1 = session.step1_req_pq_multi()
        r1 = TLReader(req1)
        self.assertEqual(r1.read_uint(), REQ_PQ_MULTI_ID)
        client_nonce = r1.read_int128_bytes()

        # Server responds with resPQ
        p_val, q_val = 104729, 104743
        pq_bytes = (p_val * q_val).to_bytes(8, "big")
        server_nonce = os.urandom(16)
        res_pq = TLWriter()
        res_pq.write_uint(RES_PQ_ID)
        res_pq.write_int128(client_nonce)
        res_pq.write_int128(server_nonce)
        res_pq.write_bytes(pq_bytes)
        res_pq.write_vector([rsa_key.fingerprint], TLWriter.write_long)

        # Client processes resPQ -> req_DH_params
        req2 = session.step2_handle_res_pq(res_pq.to_bytes())
        r2 = TLReader(req2)
        self.assertEqual(r2.read_uint(), REQ_DH_PARAMS_ID)
        self.assertEqual(r2.read_int128_bytes(), client_nonce)
        self.assertEqual(r2.read_int128_bytes(), server_nonce)
        _p_b = r2.read_bytes()
        _q_b = r2.read_bytes()
        self.assertEqual(r2.read_long(), rsa_key.fingerprint)
        enc_rsa = r2.read_bytes()

        # Server RSA-decrypts p_q_inner_data to extract new_nonce
        dec_int = pow(int.from_bytes(enc_rsa, "big"), priv_nums.d, pub_nums.n)
        dec_padded = dec_int.to_bytes(255, "big")
        pq_inner_r = TLReader(dec_padded[20:])
        self.assertEqual(pq_inner_r.read_uint(), P_Q_INNER_DATA_ID)
        _ = pq_inner_r.read_bytes()
        _ = pq_inner_r.read_bytes()
        _ = pq_inner_r.read_bytes()
        _ = pq_inner_r.read_int128_bytes()
        _ = pq_inner_r.read_int128_bytes()
        new_nonce = pq_inner_r.read_int256_bytes()

        # Server builds server_DH_params_ok using a 2048-bit prime
        dh_prime = (1 << 2047) + 981  # big 2048-bit modulus for modular exp simulation
        g = 3
        a_secret = int.from_bytes(os.urandom(32), "big")
        g_a = pow(g, a_secret, dh_prime)

        sdh_inner = TLWriter()
        sdh_inner.write_uint(SERVER_DH_INNER_DATA_ID)
        sdh_inner.write_int128(client_nonce)
        sdh_inner.write_int128(server_nonce)
        sdh_inner.write_int(g)
        sdh_inner.write_bytes(dh_prime.to_bytes(256, "big"))
        sdh_inner.write_bytes(g_a.to_bytes(256, "big"))
        sdh_inner.write_int(1700000000)
        sdh_inner_bytes = sdh_inner.to_bytes()

        sdh_with_hash = hashlib.sha1(sdh_inner_bytes).digest() + sdh_inner_bytes
        sdh_with_hash += os.urandom((-len(sdh_with_hash)) % 16)
        tmp_key, tmp_iv = derive_tmp_aes_key_iv(new_nonce, server_nonce)
        enc_sdh = aes_ige_encrypt(sdh_with_hash, tmp_key, tmp_iv)

        sdh_resp = TLWriter()
        sdh_resp.write_uint(SERVER_DH_PARAMS_OK_ID)
        sdh_resp.write_int128(client_nonce)
        sdh_resp.write_int128(server_nonce)
        sdh_resp.write_bytes(enc_sdh)

        # Client processes server_DH_params_ok -> set_client_DH_params
        req3 = session.step3_handle_server_dh_params(sdh_resp.to_bytes())
        r3 = TLReader(req3)
        self.assertEqual(r3.read_uint(), SET_CLIENT_DH_PARAMS_ID)
        self.assertEqual(r3.read_int128_bytes(), client_nonce)
        self.assertEqual(r3.read_int128_bytes(), server_nonce)
        enc_cdh = r3.read_bytes()

        # Server decrypts client_DH_inner_data and computes shared auth_key
        cdh_padded = aes_ige_decrypt(enc_cdh, tmp_key, tmp_iv)
        cdh_r = TLReader(cdh_padded[20:])
        self.assertEqual(cdh_r.read_uint(), CLIENT_DH_INNER_DATA_ID)
        _ = cdh_r.read_int128_bytes()
        _ = cdh_r.read_int128_bytes()
        _ = cdh_r.read_long()
        g_b = int.from_bytes(cdh_r.read_bytes(), "big")

        srv_auth_key = AuthKey(pow(g_b, a_secret, dh_prime).to_bytes(256, "big"))
        hash1 = hashlib.sha1(new_nonce + b"\x01" + srv_auth_key.aux_hash).digest()[4:20]

        dh_gen = TLWriter()
        dh_gen.write_uint(DH_GEN_OK_ID)
        dh_gen.write_int128(client_nonce)
        dh_gen.write_int128(server_nonce)
        dh_gen.write_int128(hash1)

        client_auth_key, server_salt = session.step4_handle_dh_gen(dh_gen.to_bytes())
        self.assertEqual(client_auth_key.key, srv_auth_key.key)
        self.assertEqual(client_auth_key.key_id, srv_auth_key.key_id)
        expected_salt = struct.unpack("<q", bytes(a ^ b for a, b in zip(new_nonce[:8], server_nonce[:8])))[0]
        self.assertEqual(server_salt, expected_salt)
