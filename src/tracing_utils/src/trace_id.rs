use pyo3::prelude::*;

use rand::rngs::OsRng;
use rand::RngCore;
use std::cell::RefCell;
use std::thread_local;
use std::time::{SystemTime, UNIX_EPOCH};
use xorshift::{Rng, SeedableRng, SplitMix64};

thread_local! {
    static TRACE_ID_RNG: RefCell<SplitMix64> = RefCell::new(SeedableRng::from_seed(OsRng.next_u64()));
}

#[pyfunction]
pub(crate) fn reseed() {
    TRACE_ID_RNG.with(|thread_rng| {
        thread_rng.borrow_mut().reseed(OsRng.next_u64());
    });
}

#[pyfunction]
pub(crate) fn gen_trace_id_64_bits() -> u64 {
    TRACE_ID_RNG.with(|thread_rng| thread_rng.borrow_mut().next_u64())
}

#[pyfunction]
pub(crate) fn gen_trace_id_128_bits() -> u128 {
    let time = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();

    (time.as_secs() as u128) << 96 | gen_trace_id_64_bits() as u128
}
