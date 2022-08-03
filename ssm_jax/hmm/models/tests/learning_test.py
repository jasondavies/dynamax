import pytest

import jax.numpy as jnp
import jax.random as jr
from jax import vmap
import optax
from ssm_jax.hmm.models import GaussianHMM

def make_rnd_hmm(num_states=5, emission_dim=2):
    # Specify parameters of the HMM
    initial_probs = jnp.ones(num_states) / num_states
    transition_matrix = 0.95 * jnp.eye(num_states) + 0.05 * jnp.roll(jnp.eye(num_states), 1, axis=1)
    emission_means = jnp.column_stack([
        jnp.cos(jnp.linspace(0, 2 * jnp.pi, num_states + 1))[:-1],
        jnp.sin(jnp.linspace(0, 2 * jnp.pi, num_states + 1))[:-1],
    ])
    emission_covs = jnp.tile(0.1**2 * jnp.eye(emission_dim), (num_states, 1, 1))

    # Make a true HMM
    true_hmm = GaussianHMM(initial_probs, transition_matrix, emission_means, emission_covs)

    return true_hmm


def make_rnd_model_and_data(num_states=5, emission_dim=2, num_timesteps=2000, num_batches=1):
    true_hmm = make_rnd_hmm(num_states, emission_dim)
    if num_batches == 1: # Keep this condition for comptaibility with earlier tests
        true_states, emissions = true_hmm.sample(jr.PRNGKey(0), num_timesteps)
        batch_true_states = true_states[None, ...]
        batch_emissions = emissions[None, ...]
    else:
        batch_true_states, batch_emissions = \
            vmap(true_hmm.sample, in_axes=(0, None))\
                (jr.split(jr.PRNGKey(0), num_batches), num_timesteps)
    return true_hmm, batch_true_states, batch_emissions


def test_loglik():
    true_hmm, true_states, batch_emissions = make_rnd_model_and_data()
    assert jnp.allclose(true_hmm.log_prob(true_states[0], batch_emissions[0]), 3149.1013, atol=1e-1)
    assert jnp.allclose(true_hmm.marginal_log_prob(batch_emissions[0]), 3149.1047, atol=1e-1)


def test_hmm_fit_em(num_iters=2):
    true_hmm, _, batch_emissions = make_rnd_model_and_data()
    test_hmm = GaussianHMM.random_initialization(jr.PRNGKey(1), 2 * true_hmm.num_states, true_hmm.num_obs)
    # Quick test: 2 iterations
    logprobs_em = test_hmm.fit_em(batch_emissions, num_iters=num_iters)
    assert jnp.allclose(logprobs_em[-1], -3704.3, atol=1e-1)
    mu = test_hmm.emission_means.value
    assert jnp.alltrue(mu.shape == (10, 2))
    assert jnp.allclose(mu[0, 0], -0.712, atol=1e-1)


def test_hmm_fit_sgd(num_epochs=2):
    true_hmm, _, batch_emissions = make_rnd_model_and_data()
    print(batch_emissions.shape)
    test_hmm = GaussianHMM.random_initialization(jr.PRNGKey(1), 2 * true_hmm.num_states, true_hmm.num_obs)
    # Quick test: 2 iterations
    optimizer = optax.adam(learning_rate=1e-2)
    losses = test_hmm.fit_sgd(batch_emissions, optimizer=optimizer, num_epochs=num_epochs)
    assert jnp.allclose(losses[-1], 1.3912, atol=1e-1)
    mu = test_hmm.emission_means.value
    assert jnp.alltrue(mu.shape == (10, 2))
    assert jnp.allclose(mu[0, 0], -1.827, atol=1e-1)

def test_hmm_fit_stochastic_em(num_iters=100):
    # Compare stochastic em fit vs. full batch fit.
    # Let stochastic em run for 2*num_iters
    true_hmm, _, batch_emissions = make_rnd_model_and_data(num_batches=8)
    print('batch_emissions.shape', batch_emissions.shape)

    refr_hmm = GaussianHMM.random_initialization(jr.PRNGKey(1), 2 * true_hmm.num_states, true_hmm.num_obs)
    test_hmm = GaussianHMM.random_initialization(jr.PRNGKey(1), 2 * true_hmm.num_states, true_hmm.num_obs)

    refr_lps = refr_hmm.fit_em(batch_emissions, num_iters)

    test_lps = test_hmm.fit_stochastic_em(
        batch_emissions, batch_size=1, num_epochs=num_iters, key=jr.PRNGKey(2),
    )

    # -------------------------------------------------------------------------
    # we expect lps to likely differ by quite a bit, but should be in the same order
    print(f'test log prob {test_lps[-1]:.2f} refrence lp {refr_lps[-1]:.2f}')
    assert jnp.allclose(test_lps[-1], refr_lps[-1], atol=100)

    refr_mu = refr_hmm.emission_means.value
    test_mu = test_hmm.emission_means.value

    assert jnp.alltrue(test_mu.shape == (10, 2))
    assert jnp.allclose(jnp.linalg.norm(test_mu-refr_mu, axis=-1), 0., atol=1)

    refr_cov = refr_hmm.emission_covariance_matrices.value
    test_cov = test_hmm.emission_covariance_matrices.value
    assert jnp.alltrue(test_cov.shape == (10, 2, 2))
    assert jnp.allclose(jnp.linalg.norm(test_cov-refr_cov, axis=-1), 0., atol=1)
