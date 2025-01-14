"""
Activity endpoint definitions

Lukas Adamowicz
Copyright (c) 2021. Pfizer Inc. All rights reserved.
"""
from numpy import (
    array,
    zeros,
    max,
    nanmax,
    histogram,
    log,
    nan,
    sum,
    nonzero,
    maximum,
    int_,
    floor,
    ceil,
)
from scipy.stats import linregress

from skdh.utility import moving_mean
from skdh.utility import fragmentation_endpoints as fe
from skdh.utility.internal import rle
from skdh.activity.cutpoints import get_level_thresholds
from skdh.activity.utility import handle_cutpoints


__all__ = [
    "ActivityEndpoint",
    "IntensityGradient",
    "MaxAcceleration",
    "TotalIntensityTime",
    "BoutIntensityTime",
    "FragmentationEndpoints",
]


def get_activity_bouts(
    accm, lower_thresh, upper_thresh, wlen, boutdur, boutcrit, closedbout, boutmetric=1
):
    """
    Get the number of bouts of activity level based on several criteria.

    Parameters
    ----------
    accm : numpy.ndarray
        Acceleration metric.
    lower_thresh : float
        Lower threshold for the activity level.
    upper_thresh : float
        Upper threshold for the activity level.
    wlen : int
        Number of seconds in the base epoch
    boutdur : int
        Number of minutes for a bout
    boutcrit : float
        Fraction of the bout that needs to be above the threshold to qualify as a bout.
    closedbout : bool
        If True then count breaks in a bout towards the bout duration. If False then
        only count time spent above the threshold towards the bout duration. Only
        used when `boutmetric` is 1.
    boutmetric : {1, 2, 3, 4, 5}, optional
        - 1: MVPA bout definition from Sabia AJE 2014 and da Silva IJE 2014. Here
            the algorithm looks for 10 minute windows in which more than XX percent
            of the epochs are above MVPA threshold and then counts the entire window
            as MVPA. The motivation for the definition 1 threshold was: A person
            who spends 10 minutes in MVPA with a 2 minute break in the middle is
            equally active as a person who spends 8 minutes in MVPA without taking
            a break. Therefore, both should be counted equal and as a 10 minute MVPA
            bout.
        - 2: Code looks for groups of epochs with a value above mvpa threshold that
            span a time window of at least mvpadur minutes in which more than `boutcrit`
            percent of the epochs are above the threshold.
        - 3: Use sliding window across the data to test bout criteria per window
            and do not allow for breaks larger than 1 minute (exactly 1 minute long
             breaks are allowed) and with fraction of time larger than the
             `boutcrit` threshold.
        - 4: same as 3 but also requires the first and last epoch to meet the threshold
            criteria.

    Returns
    -------
    bout_time : float
        Time in minutes spent in bouts of sustained MVPA.

    References
    ----------
    .. [1] I. C. da Silva et al., “Physical activity levels in three Brazilian birth
        cohorts as assessed with raw triaxial wrist accelerometry,” International
        Journal of Epidemiology, vol. 43, no. 6, pp. 1959–1968,  Dec. 2014, doi: 10.1093/ije/dyu203.
    .. [2] S. Sabia et al., “Association between questionnaire- and accelerometer-assessed
        physical activity: the role of sociodemographic factors,”
        Am J Epidemiol, vol. 179, no. 6, pp. 781–790, Mar. 2014, doi: 10.1093/aje/kwt330.
    """
    nboutdur = int(boutdur * (60 / wlen))

    time_in_bout = 0

    if accm.size < nboutdur:
        return time_in_bout

    if boutmetric == 1:
        x = ((accm >= lower_thresh) & (accm < upper_thresh)).astype(int_)
        p = nonzero(x)[0]
        i_mvpa = 0
        while i_mvpa < p.size:
            start = p[i_mvpa]
            end = start + nboutdur
            if end < x.size:
                if sum(x[start:end]) > (nboutdur * boutcrit):
                    while (
                        sum(x[start : end + 1]) > ((end + 1 - start) * boutcrit)
                    ) and (end < x.size):
                        end += 1
                    select = p[i_mvpa:][p[i_mvpa:] < end]
                    jump = maximum(select.size, 1)
                    if closedbout:
                        # +1 accounts for subtraction and actual end values
                        time_in_bout += (max(p[p < end]) - start + 1) * (wlen / 60)
                    else:
                        time_in_bout += select.size * (wlen / 60)  # in minutes
                else:
                    jump = 1
            else:
                jump = 1
            i_mvpa += jump
    elif boutmetric == 2:
        x = ((accm >= lower_thresh) & (accm < upper_thresh)).astype(int_)
        xt = zeros(x.size, dtype=int_)
        p = nonzero(x)[0]

        i_mvpa = 0
        while i_mvpa < p.size:
            start = p[i_mvpa]
            end = start + nboutdur
            if end < x.size:
                if sum(x[start:end]) > (nboutdur * boutcrit):
                    xt[start:end] = 2
                else:
                    x[start] = 0
            else:
                if p.size > 1 and i_mvpa > 2:
                    x[p[i_mvpa]] = x[p[i_mvpa - 1]]
            i_mvpa += 1
        x[xt == 2] = 1
        time_in_bout += sum(x) * (wlen / 60)  # in minutes
    elif boutmetric == 3:
        x = ((accm >= lower_thresh) & (accm < upper_thresh)).astype(int_)
        xt = x * 1  # not a view

        # look for breaks larger than 1 minute
        lookforbreaks = zeros(x.size)
        # add 1 so that breaks of exactly 1 minute are NOT excluded
        N = int(60 / wlen) + 1
        i1 = int(floor((N + 1) / 2)) - 1
        i2 = int(ceil(x.size - N / 2))
        lookforbreaks[i1:i2] = moving_mean(x, N, 1)
        # insert negative numbers to prevent these minutes from being counted in bouts
        xt[lookforbreaks == 0] = -(60 / wlen) * nboutdur
        # in this way there will not be bout breaks lasting longer than 1 minute
        try:
            # window determination can go back to left justified
            rm = moving_mean(xt, nboutdur, 1)
        except ValueError:
            return 0.0

        p = nonzero(rm > boutcrit)[0]
        for gi in range(nboutdur):
            ind = p + gi
            xt[ind[(ind >= 0) & (ind < xt.size)]] = 2
        x[xt != 2] = 0
        x[xt == 2] = 1
        time_in_bout += sum(x) * (wlen / 60)
    elif boutmetric == 4:
        x = ((accm >= lower_thresh) & (accm < upper_thresh)).astype(int_)
        xt = x * 1  # not a view
        # look for breaks longer than 1 minute
        lookforbreaks = zeros(x.size)
        # add 1 so that breaks of exactly 1 minute are NOT excluded
        N = int(60 / wlen) + 1
        i1 = int(floor((N + 1) / 2)) - 1
        i2 = int(ceil(x.size - N / 2))
        lookforbreaks[i1:i2] = moving_mean(x, N, 1)
        # insert negative numbers to prevent these minutes from being counted in bouts
        xt[lookforbreaks == 0] = -(60 / wlen) * nboutdur

        # in this way there will not be bout breaks lasting longer than 1 minute
        try:
            rm = moving_mean(xt, nboutdur, 1)
        except ValueError:
            return 0.0

        p = nonzero(rm > boutcrit)[0]
        # only get bouts where they start and end with valid values
        p = p[nonzero((x[p] == 1) & (x[p + nboutdur - 1] == 1))]
        # now mark all epochs that are covered by the remaining windows
        for gi in range(nboutdur):
            ind = p + gi
            xt[ind[nonzero((ind >= 0) & (ind < xt.size))]] = 2
        x[xt != 2] = 0
        x[xt == 2] = 1
        time_in_bout += sum(x) * (wlen / 60)
    else:
        raise ValueError("boutmetric must be in {1, 2, 3, 4}.")

    return time_in_bout


class ActivityEndpoint:
    """
    Base class for activity endpoints. Should be subclassed for creating
    custom activity endpoints.

    Attributes
    ----------
    name : {list, str}
        Name, or list of names of the endpoints being generated.
    state : {'wake', 'sleep'}
        State during which the endpoint is being computed.
    """

    def __init__(self, name, state):
        if isinstance(name, (tuple, list)):
            self.name = [f"{state} {i}" for i in name]
        else:
            self.name = f"{state} {name}"

        self.state = state

    def predict(self, **kwargs):
        """
        predict(results, i, accel_metric, epoch_s, epochs_per_min)
        Method that gets called during each block of wear time during either waking
        hours (if `state='wake'`) or sleeping hours (if `state='sleep'`). This
        means it may run multiple times per state.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        pass

    def reset_cached(self):
        """
        Called after all the blocks during the desired `state` have been run.
        Can be used to calculate results on all data for the day/state.
        """
        pass


class IntensityGradient(ActivityEndpoint):
    """
    Compute the gradient of the acceleration movement intensity.

    Parameters
    ----------
    state : {'wake', 'sleep'}
        State during which the endpoint is being computed.
    """

    def __init__(self, state="wake"):
        super(IntensityGradient, self).__init__(
            ["intensity gradient", "ig intercept", "ig r-squared"], state
        )

        # default from rowlands
        self.ig_levels = (
            array([i for i in range(0, 4001, 25)] + [8000], dtype="float") / 1000
        )
        self.ig_vals = (self.ig_levels[1:] + self.ig_levels[:-1]) / 2

        # values that need to be cached and stored between runs
        self.hist = zeros(self.ig_vals.size)
        self.ig = None
        self.ig_int = None
        self.ig_r = None
        self.i = None

    def predict(
        self,
        results,
        i,
        accel_metric,
        accel_metric_60,
        epoch_s,
        epochs_per_min,
        **kwargs,
    ):
        """
        Saves the histogram counts for each bin of acceleration intensities.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        accel_metric_60 : numpy.ndarray
            Computed acceleration metric for a 60 second window.
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        super(IntensityGradient, self).predict()

        # get the counts in number of minutes in each intensity bin
        self.hist += (
            histogram(accel_metric, bins=self.ig_levels, density=False)[0]
            / epochs_per_min
        )

        # get pointers to the intensity gradient results
        self.ig = results[self.name[0]]
        self.ig_int = results[self.name[1]]
        self.ig_r = results[self.name[2]]
        self.i = i

    def reset_cached(self):
        """
        Generate the intensity gradient metrics from the cumulative data,
        and reset the attributes.
        """
        super(IntensityGradient, self).reset_cached()

        # make sure we have results locations to set
        if all([i is not None for i in [self.ig, self.ig_int, self.ig_r, self.i]]):
            # compute the results
            # convert back to mg to match existing work
            lx = log(self.ig_vals[self.hist > 0] * 1000)
            ly = log(self.hist[self.hist > 0])

            if ly.size <= 1:
                slope = intercept = rval = nan
            else:
                slope, intercept, rval, *_ = linregress(lx, ly)

            # set the results values
            self.ig[self.i] = slope
            self.ig_int[self.i] = intercept
            self.ig_r[self.i] = rval**2

        # reset the histogram counts to 0, and results to None
        self.hist = zeros(self.ig_vals.size)
        self.ig = None
        self.ig_int = None
        self.ig_r = None
        self.i = None


class MaxAcceleration(ActivityEndpoint):
    """
    Compute the maximum acceleration over windows of the specified length.

    Parameters
    ----------
    window_lengths : {list, int}
        List of window lengths, or a single window length.
    state : {'wake', 'sleep}
        State during which the endpoint is being computed.
    """

    def __init__(self, window_lengths, state="wake"):
        if isinstance(window_lengths, int):
            window_lengths = [window_lengths]

        super().__init__([f"max acc {i}min [g]" for i in window_lengths], state)

        self.wlens = window_lengths

    def predict(
        self,
        results,
        i,
        accel_metric,
        accel_metric_60,
        epoch_s,
        epochs_per_min,
        **kwargs,
    ):
        """
        Compute the maximum acceleration during this set of data, and compare it
        to the previous largest detected value.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        accel_metric_60 : numpy.ndarray
            Computed acceleration metric for a 60 second window.
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        super(MaxAcceleration, self).predict()

        for wlen, name in zip(self.wlens, self.name):
            n = wlen * epochs_per_min
            # skip 1 sample because we want the window with the largest acceleration
            # skipping more samples would introduce bias by random chance of
            # where the windows start and stop
            try:
                tmp_max = max(moving_mean(accel_metric, n, 1))
            except ValueError:
                return  # if the window length is too long for this block of data

            # check that we don't have a larger result already for this day
            results[name][i] = nanmax([tmp_max, results[name][i]])


class TotalIntensityTime(ActivityEndpoint):
    """
    Compute the total time spent in an intensity level.

    Parameters
    ----------
    level : {"sed", "light", "mod", "vig", "MVPA", "SLPA"}
        Level of intensity to compute the total time for.
    epoch_length : int
        Number of seconds for each epoch.
    cutpoints : {str, None}
        Cutpoints to use for the thresholding. If None, will use `migueles_wrist_adult`.
    state : {'wake', 'sleep'}
        State during which the endpoint is being computed.
    """

    def __init__(self, level, epoch_length, cutpoints=None, state="wake"):
        super().__init__(f"{level} {epoch_length}s epoch [min]", state)
        self.level = level

        cutpoints = handle_cutpoints(cutpoints)

        self.lthresh, self.uthresh = get_level_thresholds(self.level, cutpoints)

    def predict(
        self,
        results,
        i,
        accel_metric,
        accel_metric_60,
        epoch_s,
        epochs_per_min,
        **kwargs,
    ):
        """
        Compute the time spent at the specified intensity level.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        accel_metric_60 : numpy.ndarray
            Computed acceleration metric for a 60 second window.
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        super().predict()

        time = sum((accel_metric >= self.lthresh) & (accel_metric < self.uthresh))

        results[self.name][i] += time / epochs_per_min


class BoutIntensityTime(ActivityEndpoint):
    """
    Compute the time spent in bouts of intensity levels.

    Parameters
    ----------
    level : {"sed", "light", "mod", "vig", "MVPA", "SLPA"}
        Level of intensity to compute the total time for.
    bout_lengths : {list, int}
        Lengths of bouts, in minutes.
    bout_criteria : float
        Percentage (0-1) of time that must be spent in the bout. See
        :class:`.ActivityLevelClassification`.
    bout_metric : {1, 2, 3, 4, 5}
        Rules for how a bout is determined. See :class:`.ActivityLevelClassification`
        for more details.
    closed_bout : bool
        Include all time for a bout or just the time at the intensity level. See
        :class:`.ActivityLevelClassification` for more details.
    cutpoints : {str, None}
        Cutpoints to use for the thresholding. If None, will use `migueles_wrist_adult`.
    state : {'wake', 'sleep'}
        State during which the endpoint is being computed.
    """

    def __init__(
        self,
        level,
        bout_lengths,
        bout_criteria,
        bout_metric,
        closed_bout,
        cutpoints=None,
        state="wake",
    ):
        if isinstance(bout_lengths, int):
            bout_lengths = [bout_lengths]

        super(BoutIntensityTime, self).__init__(
            [f"{level} {i}min bout [min]" for i in bout_lengths], state
        )
        self.level = level
        self.blens = bout_lengths
        self.bcrit = bout_criteria
        self.bmetric = bout_metric
        self.cbout = closed_bout

        cutpoints = handle_cutpoints(cutpoints)

        self.lthresh, self.uthresh = get_level_thresholds(self.level, cutpoints)

    def predict(
        self,
        results,
        i,
        accel_metric,
        accel_metric_60,
        epoch_s,
        epochs_per_min,
        **kwargs,
    ):
        """
        Compute the time spent in bouts at the specified intensity level.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        accel_metric_60 : numpy.ndarray
            Computed acceleration metric for a 60 second window.
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        super().predict()

        for bout_len, name in zip(self.blens, self.name):
            results[name][i] += get_activity_bouts(
                accel_metric,
                self.lthresh,
                self.uthresh,
                epoch_s,
                bout_len,
                self.bcrit,
                self.cbout,
                self.bmetric,
            )


class FragmentationEndpoints(ActivityEndpoint):
    """
    Compute fragmentation metrics for the desired intensity level. Fragmentation
    endpoints are computed on 1 minute windows of data.

    Parameters
    ----------
    level : {"sed", "light", "mod", "vig", "MVPA", "SLPA"}
        Level of intensity to compute the total time for.
    cutpoints : {str, None}
        Cutpoints to use for the thresholding. If None, will use `migueles_wrist_adult`.
    state : {'wake', 'sleep'}
        State during which the endpoint is being computed.
    """

    def __init__(self, level, cutpoints=None, state="wake"):
        super().__init__(
            [
                f"{level} avg duration",
                f"{level} transition probability",
                f"{level} gini index",
                f"{level} avg hazard",
                f"{level} power law distribution",
            ],
            state,
        )

        self.level = level

        cutpoints = handle_cutpoints(cutpoints)

        self.lthresh, self.uthresh = get_level_thresholds(self.level, cutpoints)

        # caching results
        self.lens = []

        self.r_ad = None  # average duration
        self.r_tp = None  # transition prob
        self.r_gi = None  # gini index
        self.r_ah = None  # avg hazard
        self.r_pld = None  # power law dist
        self.i = None

    def predict(
        self,
        results,
        i,
        accel_metric,
        accel_metric_60,
        epoch_s,
        epochs_per_min,
        **kwargs,
    ):
        """
        Compute and save the lengths of runs of the specified intensity level.

        Parameters
        ----------
        results : dict
            Dictionary containing the initialized results arrays. Keys in `results`
            are taken from the names of endpoints.
        i : int
            Index of the day, used to index into individual result arrays, e.g.
            `results[self.name][i] = 5.0`
        accel_metric : numpy.ndarray
            Computed acceleration metric (e.g. ENMO).
        accel_metric_60 : numpy.ndarray
            Computed acceleration metric for a 60 second window.
        epoch_s : int
            Duration in seconds of each sample of `accel_metric`.
        epochs_per_min : int
            Number of epochs per minute.
        """
        super().predict()

        mask = (accel_metric_60 >= self.lthresh) & (accel_metric_60 < self.uthresh)
        lens, starts, vals = rle(mask)
        # save the lengths of the desired blocks
        self.lens.extend(lens[vals == 1].tolist())

        # save pointers to the results/day info
        self.r_ad = results[f"{self.state} {self.level} avg duration"]
        self.r_tp = results[f"{self.state} {self.level} transition probability"]
        self.r_gi = results[f"{self.state} {self.level} gini index"]
        self.r_ah = results[f"{self.state} {self.level} avg hazard"]
        self.r_pld = results[f"{self.state} {self.level} power law distribution"]
        self.i = i

    def reset_cached(self):
        """
        Compute the fragmentation metrics based on the previously saved lengths
        of intensity level runs.
        """
        super().reset_cached()

        if all(
            [
                i is not None
                for i in [
                    self.r_ad,
                    self.r_tp,
                    self.r_gi,
                    self.r_ah,
                    self.r_pld,
                    self.i,
                ]
            ]
        ):
            self.r_ad[self.i] = fe.average_duration(lengths=self.lens)
            self.r_tp[self.i] = fe.state_transition_probability(lengths=self.lens)
            self.r_gi[self.i] = fe.gini_index(lengths=self.lens)
            self.r_ah[self.i] = fe.average_hazard(lengths=self.lens)
            self.r_pld[self.i] = fe.state_power_law_distribution(lengths=self.lens)

        # reset attributes
        self.lens = []
        self.r_ad = None
        self.r_tp = None
        self.r_gi = None
        self.r_ah = None
        self.r_pld = None
        self.i = None
