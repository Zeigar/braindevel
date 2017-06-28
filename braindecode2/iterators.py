import numpy as np
from numpy.random import RandomState

from braindecode2.trial_segment import compute_trial_start_end_samples


def get_balanced_batches(n_trials, rng, shuffle, n_batches=None,
                         batch_size=None):
    """Create indices for batches balanced in size (batches will have maximum size difference of 1).
    Supply either batch size or number of batches. Resulting batches
    will not have the given batch size but rather the next largest batch size
    that allows to split the set into balanced batches (maximum size difference 1).

    Parameters
    ----------
    n_trials : int
        Size of set.
    rng :

    shuffle :
        Whether to shuffle indices before splitting set.
    n_batches :
         (Default value = None)
    batch_size :
         (Default value = None)

    Returns
    -------

    """
    assert batch_size is not None or n_batches is not None
    if n_batches is None:
        n_batches = int(np.round(n_trials / float(batch_size)))

    if n_batches > 0:
        min_batch_size = n_trials // n_batches
        n_batches_with_extra_trial = n_trials % n_batches
    else:
        n_batches = 1
        min_batch_size = n_trials
        n_batches_with_extra_trial = 0
    assert n_batches_with_extra_trial < n_batches
    all_inds = np.array(range(n_trials))
    if shuffle:
        rng.shuffle(all_inds)
    i_trial = 0
    end_trial = 0
    batches = []
    for i_batch in range(n_batches):
        end_trial += min_batch_size
        if i_batch < n_batches_with_extra_trial:
            end_trial += 1
        batch_inds = all_inds[range(i_trial, end_trial)]
        batches.append(batch_inds)
        i_trial = end_trial
    assert i_trial == n_trials
    return batches


class BalancedBatchSizeIterator(object):
    """
    Create batches of balanced size.
    Parameters
    ----------
    batch_size: int
        Resulting batches will not necessarily have the given batch size
        but rather the next largest batch size that allows to split the set into
        balanced batches (maximum size difference 1).
    """
    def __init__(self, batch_size):
        self.batch_size = batch_size
        self.rng = RandomState(328774)

    def get_batches(self, dataset, shuffle):
        n_trials = dataset.X.shape[0]
        batches = get_balanced_batches(n_trials,
                                       batch_size=self.batch_size,
                                       rng=self.rng,
                                       shuffle=shuffle)
        for batch_inds in batches:
            yield (dataset.X[batch_inds], dataset.y[batch_inds])

    def reset_rng(self):
        self.rng = RandomState(328774)


class CntWindowTrialIterator(object):
    """Cut out windows for several predictions from a continous dataset
     with a trial marker y signal.

    Parameters
    ----------

    Returns
    -------

    """

    def __init__(self, batch_size, input_time_length, n_preds_per_input,
                 check_preds_smaller_trial_len=True):
        """
        
        Parameters
        ----------
        batch_size: int
        input_time_length: int
            Input time length of the ConvNet, determines size of batches in
            3rd dimension.
        n_preds_per_input: int
            Number of predictions ConvNet makes per one input. Can be computed
            by making a forward pass with the given input time length, the
            output length in 3rd dimension is n_preds_per_input.
        check_preds_smaller_trial_len: bool
        """
        self.batch_size = batch_size
        self.input_time_length = input_time_length
        self.n_preds_per_input = n_preds_per_input
        self.check_preds_smaller_trial_len = check_preds_smaller_trial_len
        self.rng = RandomState((2017,6,28))

    def reset_rng(self):
        self.rng = RandomState((2017,6,28))

    def get_batches(self, dataset, shuffle):
        i_trial_starts, i_trial_ends = compute_trial_start_end_samples(
            dataset.y, check_trial_lengths_equal=False,
            input_time_length=self.input_time_length)
        if self.check_preds_smaller_trial_len:
            self.check_trial_bounds(i_trial_starts, i_trial_ends)
        start_end_blocks_per_trial = self.compute_start_end_block_inds(
            i_trial_starts, i_trial_ends)

        return self.yield_block_batches(dataset.X, dataset.y,
                                        start_end_blocks_per_trial,
                                        shuffle=shuffle)

    def check_trial_bounds(self, i_trial_starts, i_trial_ends):
        for start, end in zip(i_trial_starts, i_trial_ends):
            assert end - start + 1 >= self.n_preds_per_input, (
                "Trial should be longer or equal than number of sample preds, "
                "Trial length: {:d}, sample preds {:d}...".
                    format(end - start + 1, self.n_preds_per_input))

    def compute_start_end_block_inds(self, i_trial_starts, i_trial_ends):
        # create start stop indices for all batches still 2d trial -> start stop
        start_end_blocks_per_trial = []
        for i_trial in range(len(i_trial_starts)):
            trial_start = i_trial_starts[i_trial]
            trial_end = i_trial_ends[i_trial]
            start_end_blocks = get_start_end_blocks_for_trial(
                trial_start, trial_end, self.input_time_length,
                self.n_preds_per_input)

            if self.check_preds_smaller_trial_len:
                # check that block is correct, all predicted samples should be the trial samples
                all_predicted_samples = [
                    range(start_end[1] - self.n_preds_per_input + 1,
                          start_end[1] + 1) for start_end in start_end_blocks]
                # this check takes about 50 ms in performance test
                # whereas loop itself takes only 5 ms.. deactivate it if not necessary
                assert np.array_equal(
                    range(i_trial_starts[i_trial], i_trial_ends[i_trial] + 1),
                    np.unique(np.concatenate(all_predicted_samples)))

            start_end_blocks_per_trial.append(start_end_blocks)
        return start_end_blocks_per_trial

    def yield_block_batches(self, X, y, start_end_blocks_per_trial, shuffle):
        start_end_blocks_flat = np.concatenate(start_end_blocks_per_trial)
        if shuffle:
            self.rng.shuffle(start_end_blocks_flat)

        for i_block in range(0, len(start_end_blocks_flat), self.batch_size):
            i_block_stop = min(i_block + self.batch_size,
                               len(start_end_blocks_flat))
            start_end_blocks = start_end_blocks_flat[i_block:i_block_stop]
            batch = create_batch(X, y, start_end_blocks, self.n_preds_per_input)
            yield batch


def get_start_end_blocks_for_trial(trial_start, trial_end, input_time_length,
                                   n_preds_per_input):
    start_end_blocks = []
    i_window_end = trial_start - 1  # now when we add sample preds in loop,
    # first sample of trial corresponds to first prediction
    while i_window_end < trial_end:
        i_window_end += n_preds_per_input
        i_adjusted_end = min(i_window_end, trial_end)
        i_window_start = i_adjusted_end - input_time_length + 1
        start_end_blocks.append((i_window_start, i_adjusted_end))

    return start_end_blocks


def create_batch(X, y, start_end_blocks, n_preds_per_input):
    for i_extra_dim in range(X.ndim, 4):
        X = X[:, :, None]
    batch_y = [y[end-n_preds_per_input+1:end+1]
        for _, end in start_end_blocks]
    batch_X = [X[start:end + 1].swapaxes(0, 2)
                  for start, end in start_end_blocks]
    # from row x time x class to row x class x time (that is output of net)
    batch_y = np.array(batch_y).swapaxes(1,2)
    batch_X = np.concatenate(batch_X).astype(np.float32)
    return batch_X, batch_y