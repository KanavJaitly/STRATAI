# Simulation tables (SIMULATION OUTPUT: synthetic truths on real schedules)

| σ/τ | Simulations | Partial | Seconds |
|---|---|---|---|
| 0.5 | 1728 | False | 1679.2 |
| 1.0 | 1728 | False | 2604.7 |
| 2.0 | 1728 | False | 1515.7 |
| 3.0 | 1728 | False | 2553.4 |

## Per-robot coverage by prior scenario (all cells pooled within σ/τ; nominal 50/80/95)

| σ/τ | Scenario | Robots | Cov50 | Cov80 | Cov95 | Width80 | Bias | RMSE | Alliance cov80 |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | indep_individual | 76956 | 0.484 | 0.777 | 0.930 | 5.66 | -0.00 | 2.47 | 0.775 |
| 0.5 | indep_population | 76956 | 0.489 | 0.787 | 0.938 | 7.16 | -0.00 | 3.21 | 0.787 |
| 0.5 | current_event_joint | 76956 | 0.485 | 0.783 | 0.936 | 7.08 | -0.00 | 3.25 | 0.781 |
| 0.5 | current_event_plugin | 76956 | 0.485 | 0.782 | 0.935 | 7.08 | -0.00 | 3.25 | 0.781 |
| 1.0 | indep_individual | 76962 | 0.491 | 0.789 | 0.940 | 8.50 | 0.01 | 3.49 | 0.784 |
| 1.0 | indep_population | 76962 | 0.492 | 0.790 | 0.942 | 11.54 | 0.01 | 4.82 | 0.787 |
| 1.0 | current_event_joint | 76962 | 0.481 | 0.777 | 0.933 | 11.32 | 0.00 | 4.89 | 0.774 |
| 1.0 | current_event_plugin | 76962 | 0.481 | 0.777 | 0.933 | 11.31 | 0.00 | 4.89 | 0.773 |
| 2.0 | indep_individual | 76968 | 0.491 | 0.790 | 0.945 | 10.93 | -0.01 | 4.37 | 0.788 |
| 2.0 | indep_population | 76968 | 0.494 | 0.793 | 0.945 | 17.13 | 0.00 | 6.86 | 0.792 |
| 2.0 | current_event_joint | 76968 | 0.464 | 0.750 | 0.907 | 16.23 | -0.01 | 7.10 | 0.751 |
| 2.0 | current_event_plugin | 76968 | 0.461 | 0.746 | 0.900 | 16.12 | -0.01 | 7.10 | 0.740 |
| 3.0 | indep_individual | 76966 | 0.496 | 0.797 | 0.948 | 11.82 | -0.00 | 4.66 | 0.794 |
| 3.0 | indep_population | 76966 | 0.494 | 0.798 | 0.947 | 20.28 | -0.02 | 8.01 | 0.789 |
| 3.0 | current_event_joint | 76966 | 0.435 | 0.707 | 0.856 | 18.31 | -0.02 | 8.44 | 0.708 |
| 3.0 | current_event_plugin | 76966 | 0.426 | 0.691 | 0.834 | 17.90 | -0.02 | 8.44 | 0.676 |

## Joint vs plug-in by matches-per-team cap (80% per-robot coverage; all noise and obs settings)

| σ/τ | Cap | Joint cov80 | Plug-in cov80 | Joint width80 | Plug-in width80 |
|---|---|---|---|---|---|
| 0.5 | cap=3 | 0.740 | 0.739 | 12.12 | 12.11 |
| 0.5 | cap=6 | 0.797 | 0.797 | 6.59 | 6.59 |
| 0.5 | cap=9 | 0.793 | 0.792 | 5.00 | 5.00 |
| 0.5 | cap=None | 0.801 | 0.801 | 4.64 | 4.64 |
| 1.0 | cap=3 | 0.734 | 0.732 | 15.73 | 15.69 |
| 1.0 | cap=6 | 0.787 | 0.787 | 11.54 | 11.54 |
| 1.0 | cap=9 | 0.793 | 0.793 | 9.36 | 9.36 |
| 1.0 | cap=None | 0.794 | 0.794 | 8.67 | 8.67 |
| 2.0 | cap=3 | 0.687 | 0.671 | 18.55 | 18.16 |
| 2.0 | cap=6 | 0.756 | 0.754 | 16.78 | 16.73 |
| 2.0 | cap=9 | 0.779 | 0.779 | 15.17 | 15.15 |
| 2.0 | cap=None | 0.779 | 0.779 | 14.44 | 14.43 |
| 3.0 | cap=3 | 0.620 | 0.573 | 19.14 | 17.96 |
| 3.0 | cap=6 | 0.706 | 0.694 | 18.61 | 18.31 |
| 3.0 | cap=9 | 0.750 | 0.747 | 18.17 | 18.07 |
| 3.0 | cap=None | 0.752 | 0.750 | 17.32 | 17.24 |

## Noise robustness (joint model, 80% per-robot and alliance coverage)

| σ/τ | Noise | Unequal obs | Robot cov80 | Alliance cov80 |
|---|---|---|---|---|
| 0.5 | none | False | 0.788 | 0.786 |
| 0.5 | none | True | 0.783 | 0.784 |
| 0.5 | robot_specific_heteroscedastic | False | 0.783 | 0.780 |
| 0.5 | robot_specific_heteroscedastic | True | 0.779 | 0.776 |
| 0.5 | shared_match_effect_rho_0.5 | False | 0.786 | 0.787 |
| 0.5 | shared_match_effect_rho_0.5 | True | 0.778 | 0.773 |
| 1.0 | none | False | 0.780 | 0.783 |
| 1.0 | none | True | 0.772 | 0.772 |
| 1.0 | robot_specific_heteroscedastic | False | 0.792 | 0.788 |
| 1.0 | robot_specific_heteroscedastic | True | 0.768 | 0.766 |
| 1.0 | shared_match_effect_rho_0.5 | False | 0.781 | 0.778 |
| 1.0 | shared_match_effect_rho_0.5 | True | 0.770 | 0.757 |
| 2.0 | none | False | 0.754 | 0.759 |
| 2.0 | none | True | 0.749 | 0.754 |
| 2.0 | robot_specific_heteroscedastic | False | 0.763 | 0.766 |
| 2.0 | robot_specific_heteroscedastic | True | 0.733 | 0.731 |
| 2.0 | shared_match_effect_rho_0.5 | False | 0.759 | 0.755 |
| 2.0 | shared_match_effect_rho_0.5 | True | 0.744 | 0.739 |
| 3.0 | none | False | 0.718 | 0.725 |
| 3.0 | none | True | 0.687 | 0.690 |
| 3.0 | robot_specific_heteroscedastic | False | 0.708 | 0.707 |
| 3.0 | robot_specific_heteroscedastic | True | 0.723 | 0.727 |
| 3.0 | shared_match_effect_rho_0.5 | False | 0.714 | 0.708 |
| 3.0 | shared_match_effect_rho_0.5 | True | 0.693 | 0.693 |

## Ignoring covariance (joint model; full vs diagonal)

| σ/τ | Cap | Alliance cov80 full | diag | Width ratio diag/full | Pair-diff cov80 full | diag | Class changed | Wrong rate full | diag | Decided full | diag |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | cap=3 | 0.731 | 0.747 | 1.030 | 0.730 | 0.733 | 0.031 | 0.056 | 0.056 | 0.570 | 0.569 |
| 0.5 | cap=6 | 0.796 | 0.806 | 1.022 | 0.796 | 0.795 | 0.009 | 0.017 | 0.017 | 0.754 | 0.754 |
| 0.5 | cap=9 | 0.788 | 0.796 | 1.020 | 0.800 | 0.798 | 0.005 | 0.009 | 0.009 | 0.796 | 0.796 |
| 0.5 | cap=None | 0.809 | 0.817 | 1.018 | 0.802 | 0.798 | 0.004 | 0.007 | 0.007 | 0.817 | 0.818 |
| 1.0 | cap=3 | 0.729 | 0.740 | 1.020 | 0.720 | 0.725 | 0.025 | 0.101 | 0.103 | 0.395 | 0.395 |
| 1.0 | cap=6 | 0.790 | 0.798 | 1.019 | 0.788 | 0.787 | 0.015 | 0.043 | 0.044 | 0.601 | 0.605 |
| 1.0 | cap=9 | 0.790 | 0.798 | 1.018 | 0.794 | 0.789 | 0.008 | 0.026 | 0.027 | 0.663 | 0.665 |
| 1.0 | cap=None | 0.787 | 0.797 | 1.018 | 0.789 | 0.786 | 0.006 | 0.027 | 0.027 | 0.686 | 0.687 |
| 2.0 | cap=3 | 0.689 | 0.680 | 0.990 | 0.662 | 0.681 | 0.010 | 0.155 | 0.155 | 0.198 | 0.197 |
| 2.0 | cap=6 | 0.753 | 0.758 | 1.010 | 0.753 | 0.750 | 0.009 | 0.083 | 0.086 | 0.339 | 0.340 |
| 2.0 | cap=9 | 0.779 | 0.785 | 1.013 | 0.772 | 0.770 | 0.010 | 0.062 | 0.063 | 0.439 | 0.441 |
| 2.0 | cap=None | 0.781 | 0.787 | 1.014 | 0.777 | 0.774 | 0.007 | 0.064 | 0.064 | 0.487 | 0.489 |
| 3.0 | cap=3 | 0.642 | 0.611 | 0.953 | 0.574 | 0.622 | 0.007 | 0.192 | 0.198 | 0.113 | 0.113 |
| 3.0 | cap=6 | 0.699 | 0.690 | 0.990 | 0.687 | 0.700 | 0.006 | 0.124 | 0.125 | 0.180 | 0.180 |
| 3.0 | cap=9 | 0.744 | 0.745 | 1.003 | 0.740 | 0.741 | 0.006 | 0.099 | 0.101 | 0.270 | 0.270 |
| 3.0 | cap=None | 0.748 | 0.749 | 1.004 | 0.741 | 0.742 | 0.005 | 0.084 | 0.084 | 0.298 | 0.299 |

## Identifiability bins (per-robot, 80% coverage and RMSE; τ = 10)

| σ/τ | Bin | n | Cov80 | RMSE | Width80 |
|---|---|---|---|---|---|
| 0.5 | current_event_joint|maxcorr=>=0.6 | 4320 | 0.605 | 5.80 | 10.02 |
| 0.5 | current_event_joint|maxcorr=[0,0.1) | 5345 | 0.809 | 1.67 | 4.01 |
| 0.5 | current_event_joint|maxcorr=[0.1,0.2) | 30418 | 0.795 | 1.93 | 4.92 |
| 0.5 | current_event_joint|maxcorr=[0.2,0.3) | 19763 | 0.798 | 2.71 | 6.65 |
| 0.5 | current_event_joint|maxcorr=[0.3,0.4) | 7972 | 0.781 | 4.54 | 10.83 |
| 0.5 | current_event_joint|maxcorr=[0.4,0.5) | 6094 | 0.792 | 4.94 | 12.51 |
| 0.5 | current_event_joint|maxcorr=[0.5,0.6) | 3044 | 0.751 | 5.18 | 12.09 |
| 0.5 | current_event_joint|n=1 | 702 | 0.741 | 7.26 | 16.88 |
| 0.5 | current_event_joint|n=10 | 4345 | 0.796 | 1.74 | 4.49 |
| 0.5 | current_event_joint|n=11 | 1198 | 0.796 | 1.58 | 4.17 |
| 0.5 | current_event_joint|n=12+ | 5271 | 0.812 | 1.50 | 3.93 |
| 0.5 | current_event_joint|n=2 | 2745 | 0.741 | 6.01 | 13.47 |
| 0.5 | current_event_joint|n=3 | 16354 | 0.739 | 5.05 | 11.58 |
| 0.5 | current_event_joint|n=4 | 1529 | 0.808 | 2.95 | 7.71 |
| 0.5 | current_event_joint|n=5 | 3393 | 0.799 | 2.73 | 6.87 |
| 0.5 | current_event_joint|n=6 | 17095 | 0.798 | 2.45 | 6.27 |
| 0.5 | current_event_joint|n=7 | 3849 | 0.803 | 2.12 | 5.46 |
| 0.5 | current_event_joint|n=8 | 5300 | 0.785 | 2.02 | 5.09 |
| 0.5 | current_event_joint|n=9 | 15175 | 0.794 | 1.85 | 4.70 |
| 0.5 | current_event_joint|partners=[0,6) | 3541 | 0.740 | 6.28 | 14.13 |
| 0.5 | current_event_joint|partners=[12,18) | 26573 | 0.797 | 2.31 | 5.88 |
| 0.5 | current_event_joint|partners=[18,24) | 20670 | 0.794 | 1.80 | 4.60 |
| 0.5 | current_event_joint|partners=[24,30) | 4651 | 0.812 | 1.49 | 3.93 |
| 0.5 | current_event_joint|partners=[6,12) | 21521 | 0.755 | 4.60 | 10.47 |
| 0.5 | current_event_joint|w_eff=>=0.9 | 56947 | 0.786 | 2.30 | 5.34 |
| 0.5 | current_event_joint|w_eff=[-1,0.2) | 30 | 0.433 | 9.74 | 9.71 |
| 0.5 | current_event_joint|w_eff=[0.2,0.4) | 173 | 0.728 | 7.49 | 17.53 |
| 0.5 | current_event_joint|w_eff=[0.4,0.5) | 361 | 0.776 | 6.55 | 16.46 |
| 0.5 | current_event_joint|w_eff=[0.5,0.6) | 1211 | 0.780 | 6.03 | 14.87 |
| 0.5 | current_event_joint|w_eff=[0.6,0.7) | 4204 | 0.792 | 5.33 | 13.69 |
| 0.5 | current_event_joint|w_eff=[0.7,0.8) | 6831 | 0.791 | 5.00 | 12.51 |
| 0.5 | current_event_joint|w_eff=[0.8,0.9) | 7199 | 0.746 | 4.54 | 9.81 |
| 0.5 | indep_individual|maxcorr=>=0.6 | 2267 | 0.347 | 4.95 | 4.41 |
| 0.5 | indep_individual|maxcorr=[0,0.1) | 7226 | 0.811 | 1.56 | 4.08 |
| 0.5 | indep_individual|maxcorr=[0.1,0.2) | 43060 | 0.797 | 2.04 | 5.15 |
| 0.5 | indep_individual|maxcorr=[0.2,0.3) | 16790 | 0.797 | 2.81 | 7.09 |
| 0.5 | indep_individual|maxcorr=[0.3,0.4) | 5190 | 0.758 | 3.23 | 7.66 |
| 0.5 | indep_individual|maxcorr=[0.4,0.5) | 1659 | 0.655 | 3.50 | 6.70 |
| 0.5 | indep_individual|maxcorr=[0.5,0.6) | 764 | 0.590 | 3.69 | 5.90 |
| 0.5 | indep_individual|n=1 | 702 | 0.701 | 4.70 | 9.83 |
| 0.5 | indep_individual|n=10 | 4345 | 0.797 | 1.65 | 4.26 |
| 0.5 | indep_individual|n=11 | 1198 | 0.790 | 1.57 | 3.99 |
| 0.5 | indep_individual|n=12+ | 5271 | 0.812 | 1.44 | 3.79 |
| 0.5 | indep_individual|n=2 | 2745 | 0.715 | 4.02 | 8.40 |
| 0.5 | indep_individual|n=3 | 16354 | 0.732 | 3.42 | 7.63 |
| 0.5 | indep_individual|n=4 | 1529 | 0.800 | 2.55 | 6.60 |
| 0.5 | indep_individual|n=5 | 3393 | 0.795 | 2.41 | 6.02 |
| 0.5 | indep_individual|n=6 | 17095 | 0.794 | 2.19 | 5.59 |
| 0.5 | indep_individual|n=7 | 3849 | 0.786 | 1.99 | 5.04 |
| 0.5 | indep_individual|n=8 | 5300 | 0.792 | 1.88 | 4.75 |
| 0.5 | indep_individual|n=9 | 15175 | 0.788 | 1.75 | 4.43 |
| 0.5 | indep_individual|partners=[0,6) | 3541 | 0.712 | 4.16 | 8.66 |
| 0.5 | indep_individual|partners=[12,18) | 26573 | 0.793 | 2.09 | 5.31 |
| 0.5 | indep_individual|partners=[18,24) | 20670 | 0.791 | 1.71 | 4.35 |
| 0.5 | indep_individual|partners=[24,30) | 4651 | 0.813 | 1.44 | 3.79 |
| 0.5 | indep_individual|partners=[6,12) | 21521 | 0.748 | 3.21 | 7.27 |
| 0.5 | indep_individual|w_eff=>=0.9 | 9494 | 0.720 | 2.22 | 3.71 |
| 0.5 | indep_individual|w_eff=[-1,0.2) | 76 | 0.842 | 4.17 | 11.71 |
| 0.5 | indep_individual|w_eff=[0.2,0.4) | 1342 | 0.833 | 3.84 | 10.49 |
| 0.5 | indep_individual|w_eff=[0.4,0.5) | 3376 | 0.834 | 3.42 | 9.45 |
| 0.5 | indep_individual|w_eff=[0.5,0.6) | 5236 | 0.817 | 3.20 | 8.57 |
| 0.5 | indep_individual|w_eff=[0.6,0.7) | 5218 | 0.767 | 3.18 | 7.59 |
| 0.5 | indep_individual|w_eff=[0.7,0.8) | 12483 | 0.785 | 2.59 | 6.22 |
| 0.5 | indep_individual|w_eff=[0.8,0.9) | 39731 | 0.778 | 2.08 | 4.83 |
| 1.0 | current_event_joint|maxcorr=>=0.6 | 972 | 0.422 | 8.95 | 10.27 |
| 1.0 | current_event_joint|maxcorr=[0,0.1) | 8458 | 0.774 | 3.74 | 8.24 |
| 1.0 | current_event_joint|maxcorr=[0.1,0.2) | 43199 | 0.787 | 4.16 | 10.10 |
| 1.0 | current_event_joint|maxcorr=[0.2,0.3) | 16576 | 0.781 | 5.67 | 13.83 |
| 1.0 | current_event_joint|maxcorr=[0.3,0.4) | 5382 | 0.779 | 6.68 | 16.46 |
| 1.0 | current_event_joint|maxcorr=[0.4,0.5) | 1817 | 0.735 | 7.10 | 15.90 |
| 1.0 | current_event_joint|maxcorr=[0.5,0.6) | 558 | 0.685 | 7.50 | 15.35 |
| 1.0 | current_event_joint|n=1 | 611 | 0.704 | 9.11 | 19.82 |
| 1.0 | current_event_joint|n=10 | 4426 | 0.796 | 3.28 | 8.33 |
| 1.0 | current_event_joint|n=11 | 1140 | 0.796 | 3.12 | 7.94 |
| 1.0 | current_event_joint|n=12+ | 5278 | 0.799 | 2.97 | 7.61 |
| 1.0 | current_event_joint|n=2 | 2789 | 0.730 | 7.58 | 17.04 |
| 1.0 | current_event_joint|n=3 | 16391 | 0.737 | 6.75 | 15.32 |
| 1.0 | current_event_joint|n=4 | 1466 | 0.775 | 5.33 | 13.06 |
| 1.0 | current_event_joint|n=5 | 3463 | 0.774 | 4.79 | 11.93 |
| 1.0 | current_event_joint|n=6 | 17100 | 0.790 | 4.42 | 11.15 |
| 1.0 | current_event_joint|n=7 | 3827 | 0.790 | 4.01 | 10.06 |
| 1.0 | current_event_joint|n=8 | 5248 | 0.791 | 3.75 | 9.44 |
| 1.0 | current_event_joint|n=9 | 15223 | 0.795 | 3.49 | 8.88 |
| 1.0 | current_event_joint|partners=[0,6) | 3491 | 0.725 | 7.89 | 17.48 |
| 1.0 | current_event_joint|partners=[12,18) | 26450 | 0.791 | 4.21 | 10.59 |
| 1.0 | current_event_joint|partners=[18,24) | 20768 | 0.794 | 3.42 | 8.67 |
| 1.0 | current_event_joint|partners=[24,30) | 4663 | 0.800 | 2.96 | 7.60 |
| 1.0 | current_event_joint|partners=[6,12) | 21590 | 0.747 | 6.35 | 14.56 |
| 1.0 | current_event_joint|w_eff=>=0.9 | 9333 | 0.754 | 3.83 | 8.01 |
| 1.0 | current_event_joint|w_eff=[-1,0.2) | 449 | 0.452 | 8.47 | 10.71 |
| 1.0 | current_event_joint|w_eff=[0.2,0.4) | 1964 | 0.680 | 7.60 | 15.46 |
| 1.0 | current_event_joint|w_eff=[0.4,0.5) | 3335 | 0.743 | 7.04 | 16.27 |
| 1.0 | current_event_joint|w_eff=[0.5,0.6) | 6051 | 0.792 | 6.44 | 16.45 |
| 1.0 | current_event_joint|w_eff=[0.6,0.7) | 6575 | 0.772 | 6.19 | 15.01 |
| 1.0 | current_event_joint|w_eff=[0.7,0.8) | 12130 | 0.786 | 4.99 | 12.20 |
| 1.0 | current_event_joint|w_eff=[0.8,0.9) | 37125 | 0.790 | 3.98 | 9.72 |
| 1.0 | indep_individual|maxcorr=>=0.6 | 464 | 0.192 | 8.54 | 4.08 |
| 1.0 | indep_individual|maxcorr=[0,0.1) | 37544 | 0.802 | 3.07 | 7.88 |
| 1.0 | indep_individual|maxcorr=[0.1,0.2) | 35428 | 0.795 | 3.66 | 9.19 |
| 1.0 | indep_individual|maxcorr=[0.2,0.3) | 2730 | 0.713 | 4.33 | 9.18 |
| 1.0 | indep_individual|maxcorr=[0.3,0.4) | 476 | 0.603 | 4.90 | 7.91 |
| 1.0 | indep_individual|maxcorr=[0.4,0.5) | 210 | 0.405 | 6.46 | 6.86 |
| 1.0 | indep_individual|maxcorr=[0.5,0.6) | 110 | 0.336 | 6.17 | 5.97 |
| 1.0 | indep_individual|n=1 | 611 | 0.736 | 5.44 | 11.42 |
| 1.0 | indep_individual|n=10 | 4426 | 0.798 | 2.82 | 7.17 |
| 1.0 | indep_individual|n=11 | 1140 | 0.793 | 2.69 | 6.93 |
| 1.0 | indep_individual|n=12+ | 5278 | 0.809 | 2.59 | 6.73 |
| 1.0 | indep_individual|n=2 | 2789 | 0.774 | 4.53 | 10.58 |
| 1.0 | indep_individual|n=3 | 16391 | 0.762 | 4.30 | 9.98 |
| 1.0 | indep_individual|n=4 | 1466 | 0.816 | 3.68 | 9.52 |
| 1.0 | indep_individual|n=5 | 3463 | 0.796 | 3.55 | 9.00 |
| 1.0 | indep_individual|n=6 | 17100 | 0.794 | 3.41 | 8.62 |
| 1.0 | indep_individual|n=7 | 3827 | 0.798 | 3.22 | 8.16 |
| 1.0 | indep_individual|n=8 | 5248 | 0.798 | 3.04 | 7.81 |
| 1.0 | indep_individual|n=9 | 15223 | 0.797 | 2.91 | 7.49 |
| 1.0 | indep_individual|partners=[0,6) | 3491 | 0.765 | 4.70 | 10.72 |
| 1.0 | indep_individual|partners=[12,18) | 26450 | 0.796 | 3.30 | 8.36 |
| 1.0 | indep_individual|partners=[18,24) | 20768 | 0.797 | 2.87 | 7.37 |
| 1.0 | indep_individual|partners=[24,30) | 4663 | 0.809 | 2.59 | 6.72 |
| 1.0 | indep_individual|partners=[6,12) | 21590 | 0.772 | 4.14 | 9.77 |
| 1.0 | indep_individual|w_eff=>=0.9 | 216 | 0.093 | 9.41 | 2.69 |
| 1.0 | indep_individual|w_eff=[-1,0.2) | 1034 | 0.805 | 4.51 | 11.76 |
| 1.0 | indep_individual|w_eff=[0.2,0.4) | 13318 | 0.806 | 4.11 | 10.62 |
| 1.0 | indep_individual|w_eff=[0.4,0.5) | 9348 | 0.796 | 3.76 | 9.42 |
| 1.0 | indep_individual|w_eff=[0.5,0.6) | 18753 | 0.792 | 3.42 | 8.57 |
| 1.0 | indep_individual|w_eff=[0.6,0.7) | 25615 | 0.792 | 3.03 | 7.56 |
| 1.0 | indep_individual|w_eff=[0.7,0.8) | 8423 | 0.769 | 2.92 | 6.68 |
| 1.0 | indep_individual|w_eff=[0.8,0.9) | 255 | 0.235 | 7.53 | 4.89 |
| 2.0 | current_event_joint|maxcorr=>=0.6 | 1843 | 0.169 | 9.79 | 4.23 |
| 2.0 | current_event_joint|maxcorr=[0,0.1) | 43778 | 0.753 | 6.54 | 14.94 |
| 2.0 | current_event_joint|maxcorr=[0.1,0.2) | 25902 | 0.786 | 7.27 | 18.06 |
| 2.0 | current_event_joint|maxcorr=[0.2,0.3) | 3944 | 0.775 | 8.65 | 21.87 |
| 2.0 | current_event_joint|maxcorr=[0.3,0.4) | 1212 | 0.709 | 10.15 | 22.10 |
| 2.0 | current_event_joint|maxcorr=[0.4,0.5) | 222 | 0.676 | 10.83 | 22.73 |
| 2.0 | current_event_joint|maxcorr=[0.5,0.6) | 67 | 0.522 | 13.84 | 20.18 |
| 2.0 | current_event_joint|n=1 | 611 | 0.664 | 9.79 | 20.70 |
| 2.0 | current_event_joint|n=10 | 4393 | 0.784 | 5.74 | 14.34 |
| 2.0 | current_event_joint|n=11 | 1301 | 0.772 | 5.63 | 13.58 |
| 2.0 | current_event_joint|n=12+ | 5260 | 0.786 | 5.25 | 13.15 |
| 2.0 | current_event_joint|n=2 | 2825 | 0.693 | 9.01 | 19.66 |
| 2.0 | current_event_joint|n=3 | 16371 | 0.690 | 8.69 | 18.31 |
| 2.0 | current_event_joint|n=4 | 1462 | 0.758 | 7.90 | 18.19 |
| 2.0 | current_event_joint|n=5 | 3360 | 0.757 | 7.39 | 17.29 |
| 2.0 | current_event_joint|n=6 | 17200 | 0.759 | 6.95 | 16.52 |
| 2.0 | current_event_joint|n=7 | 3860 | 0.779 | 6.55 | 15.91 |
| 2.0 | current_event_joint|n=8 | 5153 | 0.774 | 6.30 | 15.24 |
| 2.0 | current_event_joint|n=9 | 15172 | 0.778 | 6.00 | 14.68 |
| 2.0 | current_event_joint|partners=[0,6) | 3522 | 0.688 | 9.16 | 19.86 |
| 2.0 | current_event_joint|partners=[12,18) | 26520 | 0.764 | 6.76 | 16.13 |
| 2.0 | current_event_joint|partners=[18,24) | 20829 | 0.780 | 5.89 | 14.49 |
| 2.0 | current_event_joint|partners=[24,30) | 4646 | 0.788 | 5.22 | 13.18 |
| 2.0 | current_event_joint|partners=[6,12) | 21451 | 0.706 | 8.41 | 18.11 |
| 2.0 | current_event_joint|w_eff=>=0.9 | 1801 | 0.156 | 9.72 | 3.80 |
| 2.0 | current_event_joint|w_eff=[-1,0.2) | 4431 | 0.547 | 8.81 | 13.65 |
| 2.0 | current_event_joint|w_eff=[0.2,0.4) | 11677 | 0.736 | 7.95 | 18.22 |
| 2.0 | current_event_joint|w_eff=[0.4,0.5) | 9961 | 0.777 | 7.42 | 18.23 |
| 2.0 | current_event_joint|w_eff=[0.5,0.6) | 17085 | 0.789 | 6.80 | 16.93 |
| 2.0 | current_event_joint|w_eff=[0.6,0.7) | 19236 | 0.794 | 6.42 | 15.97 |
| 2.0 | current_event_joint|w_eff=[0.7,0.8) | 11385 | 0.787 | 6.17 | 15.10 |
| 2.0 | current_event_joint|w_eff=[0.8,0.9) | 1392 | 0.720 | 6.52 | 13.94 |
| 2.0 | indep_individual|maxcorr=>=0.6 | 31 | 0.129 | 13.95 | 3.80 |
| 2.0 | indep_individual|maxcorr=[0,0.1) | 75341 | 0.793 | 4.34 | 10.94 |
| 2.0 | indep_individual|maxcorr=[0.1,0.2) | 1426 | 0.722 | 5.00 | 10.75 |
| 2.0 | indep_individual|maxcorr=[0.2,0.3) | 122 | 0.549 | 7.00 | 9.30 |
| 2.0 | indep_individual|maxcorr=[0.3,0.4) | 9 | 0.444 | 4.25 | 8.29 |
| 2.0 | indep_individual|maxcorr=[0.4,0.5) | 22 | 0.227 | 11.82 | 5.77 |
| 2.0 | indep_individual|maxcorr=[0.5,0.6) | 17 | 0.118 | 11.56 | 5.63 |
| 2.0 | indep_individual|n=1 | 611 | 0.807 | 4.86 | 12.40 |
| 2.0 | indep_individual|n=10 | 4393 | 0.800 | 4.01 | 10.22 |
| 2.0 | indep_individual|n=11 | 1301 | 0.766 | 4.09 | 9.99 |
| 2.0 | indep_individual|n=12+ | 5260 | 0.792 | 3.88 | 9.81 |
| 2.0 | indep_individual|n=2 | 2825 | 0.793 | 4.87 | 12.03 |
| 2.0 | indep_individual|n=3 | 16371 | 0.782 | 4.80 | 11.71 |
| 2.0 | indep_individual|n=4 | 1462 | 0.776 | 4.69 | 11.52 |
| 2.0 | indep_individual|n=5 | 3360 | 0.789 | 4.50 | 11.26 |
| 2.0 | indep_individual|n=6 | 17200 | 0.792 | 4.37 | 11.04 |
| 2.0 | indep_individual|n=7 | 3860 | 0.793 | 4.23 | 10.82 |
| 2.0 | indep_individual|n=8 | 5153 | 0.785 | 4.21 | 10.59 |
| 2.0 | indep_individual|n=9 | 15172 | 0.797 | 4.08 | 10.38 |
| 2.0 | indep_individual|partners=[0,6) | 3522 | 0.794 | 4.87 | 12.09 |
| 2.0 | indep_individual|partners=[12,18) | 26520 | 0.790 | 4.32 | 10.91 |
| 2.0 | indep_individual|partners=[18,24) | 20829 | 0.795 | 4.06 | 10.30 |
| 2.0 | indep_individual|partners=[24,30) | 4646 | 0.797 | 3.85 | 9.82 |
| 2.0 | indep_individual|partners=[6,12) | 21451 | 0.784 | 4.74 | 11.61 |
| 2.0 | indep_individual|w_eff=>=0.9 | 21 | 0.143 | 13.60 | 3.13 |
| 2.0 | indep_individual|w_eff=[-1,0.2) | 19343 | 0.797 | 4.68 | 11.91 |
| 2.0 | indep_individual|w_eff=[0.2,0.4) | 51869 | 0.791 | 4.26 | 10.71 |
| 2.0 | indep_individual|w_eff=[0.4,0.5) | 5509 | 0.771 | 4.01 | 9.67 |
| 2.0 | indep_individual|w_eff=[0.5,0.6) | 176 | 0.659 | 5.50 | 8.90 |
| 2.0 | indep_individual|w_eff=[0.6,0.7) | 1 | 0.000 | 27.89 | 7.12 |
| 2.0 | indep_individual|w_eff=[0.7,0.8) | 9 | 0.000 | 11.68 | 6.26 |
| 2.0 | indep_individual|w_eff=[0.8,0.9) | 40 | 0.200 | 11.61 | 5.13 |
| 3.0 | current_event_joint|maxcorr=>=0.6 | 6165 | 0.176 | 9.81 | 4.39 |
| 3.0 | current_event_joint|maxcorr=[0,0.1) | 58628 | 0.756 | 7.94 | 18.66 |
| 3.0 | current_event_joint|maxcorr=[0.1,0.2) | 9475 | 0.778 | 9.36 | 23.97 |
| 3.0 | current_event_joint|maxcorr=[0.2,0.3) | 1640 | 0.704 | 11.09 | 25.73 |
| 3.0 | current_event_joint|maxcorr=[0.3,0.4) | 637 | 0.590 | 12.16 | 22.39 |
| 3.0 | current_event_joint|maxcorr=[0.4,0.5) | 276 | 0.297 | 11.38 | 10.03 |
| 3.0 | current_event_joint|maxcorr=[0.5,0.6) | 145 | 0.345 | 13.67 | 14.09 |
| 3.0 | current_event_joint|n=1 | 620 | 0.629 | 10.55 | 21.70 |
| 3.0 | current_event_joint|n=10 | 4424 | 0.766 | 7.32 | 17.31 |
| 3.0 | current_event_joint|n=11 | 1168 | 0.733 | 7.36 | 16.40 |
| 3.0 | current_event_joint|n=12+ | 5244 | 0.773 | 6.90 | 16.51 |
| 3.0 | current_event_joint|n=2 | 2742 | 0.631 | 10.29 | 20.49 |
| 3.0 | current_event_joint|n=3 | 16417 | 0.621 | 9.73 | 18.87 |
| 3.0 | current_event_joint|n=4 | 1498 | 0.707 | 8.95 | 19.57 |
| 3.0 | current_event_joint|n=5 | 3503 | 0.718 | 8.58 | 19.29 |
| 3.0 | current_event_joint|n=6 | 17070 | 0.711 | 8.43 | 18.52 |
| 3.0 | current_event_joint|n=7 | 3804 | 0.750 | 7.99 | 18.62 |
| 3.0 | current_event_joint|n=8 | 5327 | 0.746 | 7.75 | 18.14 |
| 3.0 | current_event_joint|n=9 | 15149 | 0.746 | 7.55 | 17.64 |
| 3.0 | current_event_joint|partners=[0,6) | 3447 | 0.632 | 10.32 | 20.76 |
| 3.0 | current_event_joint|partners=[12,18) | 26514 | 0.724 | 8.20 | 18.40 |
| 3.0 | current_event_joint|partners=[18,24) | 20668 | 0.752 | 7.48 | 17.53 |
| 3.0 | current_event_joint|partners=[24,30) | 4637 | 0.773 | 6.87 | 16.48 |
| 3.0 | current_event_joint|partners=[6,12) | 21700 | 0.642 | 9.49 | 18.95 |
| 3.0 | current_event_joint|w_eff=>=0.9 | 6184 | 0.172 | 9.67 | 4.19 |
| 3.0 | current_event_joint|w_eff=[-1,0.2) | 12630 | 0.587 | 8.94 | 15.21 |
| 3.0 | current_event_joint|w_eff=[0.2,0.4) | 24851 | 0.763 | 8.30 | 20.06 |
| 3.0 | current_event_joint|w_eff=[0.4,0.5) | 15252 | 0.812 | 8.02 | 20.98 |
| 3.0 | current_event_joint|w_eff=[0.5,0.6) | 12105 | 0.818 | 7.89 | 20.69 |
| 3.0 | current_event_joint|w_eff=[0.6,0.7) | 5159 | 0.801 | 8.33 | 20.61 |
| 3.0 | current_event_joint|w_eff=[0.7,0.8) | 713 | 0.760 | 9.43 | 20.35 |
| 3.0 | current_event_joint|w_eff=[0.8,0.9) | 72 | 0.472 | 17.58 | 21.65 |
| 3.0 | indep_individual|maxcorr=[0,0.1) | 76809 | 0.798 | 4.64 | 11.83 |
| 3.0 | indep_individual|maxcorr=[0.1,0.2) | 92 | 0.500 | 8.08 | 10.01 |
| 3.0 | indep_individual|maxcorr=[0.2,0.3) | 16 | 0.500 | 6.64 | 9.60 |
| 3.0 | indep_individual|maxcorr=[0.3,0.4) | 45 | 0.156 | 12.61 | 7.99 |
| 3.0 | indep_individual|maxcorr=[0.4,0.5) | 4 | 0.250 | 10.16 | 10.12 |
| 3.0 | indep_individual|n=1 | 620 | 0.769 | 5.29 | 12.59 |
| 3.0 | indep_individual|n=10 | 4424 | 0.808 | 4.44 | 11.41 |
| 3.0 | indep_individual|n=11 | 1168 | 0.777 | 4.64 | 11.29 |
| 3.0 | indep_individual|n=12+ | 5244 | 0.791 | 4.40 | 11.14 |
| 3.0 | indep_individual|n=2 | 2742 | 0.802 | 4.93 | 12.42 |
| 3.0 | indep_individual|n=3 | 16417 | 0.796 | 4.89 | 12.26 |
| 3.0 | indep_individual|n=4 | 1498 | 0.808 | 4.65 | 12.19 |
| 3.0 | indep_individual|n=5 | 3503 | 0.798 | 4.70 | 12.03 |
| 3.0 | indep_individual|n=6 | 17070 | 0.795 | 4.67 | 11.91 |
| 3.0 | indep_individual|n=7 | 3804 | 0.794 | 4.63 | 11.77 |
| 3.0 | indep_individual|n=8 | 5327 | 0.791 | 4.59 | 11.64 |
| 3.0 | indep_individual|n=9 | 15149 | 0.802 | 4.46 | 11.51 |
| 3.0 | indep_individual|partners=[0,6) | 3447 | 0.795 | 4.99 | 12.44 |
| 3.0 | indep_individual|partners=[12,18) | 26514 | 0.795 | 4.64 | 11.82 |
| 3.0 | indep_individual|partners=[18,24) | 20668 | 0.800 | 4.48 | 11.47 |
| 3.0 | indep_individual|partners=[24,30) | 4637 | 0.793 | 4.38 | 11.14 |
| 3.0 | indep_individual|partners=[6,12) | 21700 | 0.797 | 4.84 | 12.21 |
| 3.0 | indep_individual|w_eff=[-1,0.2) | 61211 | 0.799 | 4.68 | 11.98 |
| 3.0 | indep_individual|w_eff=[0.2,0.4) | 15633 | 0.791 | 4.49 | 11.25 |
| 3.0 | indep_individual|w_eff=[0.4,0.5) | 77 | 0.455 | 8.16 | 9.64 |
| 3.0 | indep_individual|w_eff=[0.5,0.6) | 10 | 0.100 | 14.39 | 8.57 |
| 3.0 | indep_individual|w_eff=[0.6,0.7) | 35 | 0.171 | 11.79 | 7.66 |
