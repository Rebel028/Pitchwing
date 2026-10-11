# Credible callback timing on macOS

Research note for wayfinder ticket 02 (`.scratch/apple-silicon/issues/02-research-macos-realtime-timing.md`), written 2026-10-11 on the target machine: Apple M4 Pro, 10 performance and 4 efficiency cores (`sysctl hw.perflevel0.logicalcpu` = 10, `hw.perflevel1.logicalcpu` = 4), macOS 26.5.1 build 25F80, kernel `xnu-12377.121.6~2/RELEASE_ARM64_T6041` (`uname -v`). XNU citations below are to the `apple-oss-distributions/xnu` tag `xnu-12377.121.6` (commit `f6217f891ac0bb64f3d375211650a4c1ff8ca1ea` on `main` at the time of reading), which is the same release as the running kernel. SDK header paths are under `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`, a symlink to `MacOSX26.5.sdk`.

## Conclusion

A minimal change is needed, and it is two calls, not a redesign:

1. Put the probe thread into the Mach time constraint band with `thread_policy_set(THREAD_TIME_CONSTRAINT_POLICY)` before each case, with `period` = `block / rate`, `constraint` = `period`, and `computation` = `max(period / 2, 50 us)`, all converted to Mach absolute time units through `mach_timebase_info`.
2. Pace the loop so the thread blocks once per callback (`mach_wait_until` to the next period boundary) instead of spinning through all cases.

Without step 1 the probe runs as a default QoS timeshare thread, which the scheduler may place on any core type and preempt at will; with it the thread is in the same scheduling mode (`TH_MODE_REALTIME`, priority band 97 and above) that a Core Audio client render thread must be in to join the device work interval. Without step 2 a real time thread that never blocks trips the kernel fail safe after 1 s of continuous computation and is silently demoted to timeshare, which would make the "after" numbers no better than the "before" numbers.

No clock change is needed: `std::chrono::steady_clock` and `mach_absolute_time` read the same 24 MHz counter on this machine and differ only by a constant sleep offset. Timer coalescing cannot affect the probe's per callback durations because the probe never sets a timer; it affects wake up jitter, which the current probe does not measure at all. Audio workgroups are the one thing the probe cannot reproduce on its own without creating a work interval, and that is left as an optional follow up.

Everything below is the evidence for those statements. Each fact is stated once, where its source is cited.

## What the probe measures today

`tools/pitchwing_live_probe.cpp` lines 56 to 71 take `std::chrono::steady_clock::now()` before and after processing one host block, record the microseconds, and count a deadline miss when the duration exceeds `block / rate`. The thread is `main` with no scheduling calls (`tools/pitchwing_live_probe.cpp` lines 181 to 193), the cases loop without blocking (lines 29 to 75), and the JSON header labels the clock as `steady_clock` (line 24). Cases are 44.1, 48 and 96 kHz with blocks 1, 32, 64 and 128 (lines 29 and 46), so the periods range from 10.4 us (block 1 at 96 kHz) to 2.90 ms (block 128 at 44.1 kHz).

## How Core Audio and host render threads are scheduled

### The I/O thread and the client render thread are real time threads in a workgroup

Apple's AudioToolbox header describes the model: "Workgroups express that a collection of realtime threads are working in tandem to produce audio for a common deadline. Such threads span multiple processes including the audio server and client applications. The system uses workgroups to observe the CPU usage of audio realtime threads and dynamically balance the competing considerations of power consumption vs. rendering capacity" (`System/Library/Frameworks/AudioToolbox.framework/Headers/AudioWorkInterval.h` lines 8 to 12). The same header calls the HAL thread "the Core Audio realtime I/O thread" (lines 29 to 30) and says that every Core Audio device owns a workgroup exposed as `kAudioDevicePropertyIOThreadOSWorkgroup` (lines 17 to 18; the property is declared in `System/Library/Frameworks/CoreAudio.framework/Headers/AudioHardware.h` lines 987 to 990).

Apple's "Understanding Audio Workgroups" article adds the cadence: the I/O thread "wakes up at regular intervals and calls its associated client app to retrieve its audio output. When the client finishes rendering its audio, the system writes it to the output hardware, and the I/O thread sleeps. If a client takes too long to produce audio, the thread misses its deadline, which results in an audio overload"; "For every audio server I/O thread, its associated app also has its own real-time render thread"; "The system automatically joins the client app's real-time thread to the audio device's workgroup"; and "Only real-time threads can join an audio workgroup; nonreal-time threads cannot" (<https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups>, read through the `tutorials/data/...json` endpoint).

The kernel enforces the last sentence: joining a work interval of type `WORK_INTERVAL_TYPE_COREAUDIO` returns `KERN_INVALID_ARGUMENT` unless the thread's scheduling mode is `TH_MODE_REALTIME` (`osfmk/kern/work_interval.c` lines 881 to 884), and the only user level path that sets `TH_MODE_REALTIME` is the `THREAD_TIME_CONSTRAINT_POLICY` case of `thread_policy_set` (`osfmk/kern/thread_policy.c` line 449). So the Core Audio client render thread that calls a plug-in's process function is, by construction, a time constraint thread.

The buffer that sets the period is `kAudioDevicePropertyBufferFrameSize`, "the number of frames in the IO buffers" (`AudioHardware.h` lines 945 to 946). The client is only given part of each cycle: `kAudioDevicePropertyIOCycleUsage` is "how much of the client portion of the IO cycle the process will use. The client portion of the IO cycle is the portion of the cycle in which the device calls the IOProcs" (`AudioHardware.h` lines 960 to 965).

### Audio Unit hosts may render from a real time thread, a real time thread outside any workgroup, or a non real time thread

`AURenderContextObserver` is called "from the render thread, immediately before any render request which is in a context (workgroup) differing from the previous one", and "The new workgroup may be null in the case of a non-realtime render context, or a realtime thread which is not part of any workgroup" (`System/Library/Frameworks/AudioToolbox.framework/Headers/AudioUnitProperties.h` lines 1380 to 1397). Apple's WWDC20 session 10224 states the same for plug-ins ("the Audio Unit has realtime threads that are not part of a workgroup") and that "all audio threads should be joined to workgroups" (<https://developer.apple.com/videos/play/wwdc2020/10224/>, transcript). No Apple primary source describes how a specific DAW schedules its VST3 or AU worker threads; see the open questions.

### Time constraint policy semantics

The SDK header defines the four fields: `period` is "the nominal amount of time between separate processing arrivals, specified in absolute time units. A value of 0 indicates that there is no inherent periodicity"; `computation` is "the nominal amount of computation time needed during a separate processing arrival ... The thread may be preempted after the computation time has elapsed. If (computation < constraint/2) it will be forced to constraint/2 to avoid unintended preemption and associated timer interrupts"; `constraint` is "the maximum amount of real time that may elapse from the start of a separate processing arrival to the end of computation for logically correct functioning ... Must be (>= computation). Note that latency = (constraint - computation)"; and `preemptible` is "IGNORED" (`usr/include/mach/thread_policy.h` lines 120 to 157).

The kernel implementation of that header, at the tag matching this machine:

- Validation rejects `constraint < computation`, `computation > max_rt_quantum` and `computation < min_rt_quantum` with `KERN_INVALID_ARGUMENT` (`osfmk/kern/thread_policy.c` lines 407 to 412). `min_rt_quantum` is 50 us and `max_rt_quantum` is 50 ms (`osfmk/kern/sched_rt.c` lines 103 to 112). `period` is stored but never validated (lines 407 to 432 contain no test of it).
- `computation` below `constraint / 2` is raised to `constraint / 2`, capped at `max_rt_quantum` (`thread_policy.c` lines 415 to 419).
- The thread's mode becomes `TH_MODE_REALTIME` and its base priority is `BASEPRI_RTQUEUES` plus a zero offset (`thread_policy.c` lines 432 to 449; `BASEPRI_RTQUEUES` is 97 in `osfmk/kern/sched.h` line 143).
- A QoS class set earlier on the thread is removed before the real time policy is applied, and restored only if the call fails (`thread_policy.c` lines 312 to 328). Apple's QoS classes are therefore not an alternative to the time constraint policy; they are a separate band below it (`usr/include/sys/qos.h` lines 56 to 105 describe the five classes as priorities relative to each other and energy efficiency hints, with no deadline semantics).
- Each time the thread becomes runnable its deadline is `constraint + mach_absolute_time()` (`osfmk/kern/sched_prim.c` lines 862 to 865, in `thread_unblock`), and its quantum is `computation` (`sched_prim.c` lines 3934 to 3935). When the quantum is used up the deadline is cancelled and the thread competes with other real time threads as "quantum expired" (`sched_prim.c` lines 3480 to 3487).
- The fail safe: at quantum expiry, a `TH_MODE_REALTIME` thread whose continuous on core computation since it last blocked exceeds `max_unsafe_rt_computation` is demoted with `TH_SFLAG_FAILSAFE` (`osfmk/kern/priority.c` lines 158 to 193). `max_unsafe_rt_computation` is `max_unsafe_rt_quanta` times the standard quantum (`sched_prim.c` line 522); `max_unsafe_rt_quanta` defaults to 100 (`sched_prim.c` line 156) and the standard quantum is 1 s divided by `default_preemption_rate` = 100, that is 10 ms (`sched_prim.c` lines 146 to 147 and 501; `sched_clutch.c` lines 3264 to 3268 return that `std_quantum`). Blocking resets the accounting (`sched_prim.c` line 873 zeroes `computation_metered` in `thread_unblock`). The demotion is logged as "triggered fail-safe by spinning for at least ... us at realtime priority" (`sched_prim.c` lines 6865 to 6875). Apple's archived scheduler guide says the same in prose: a real time thread "is penalized (and may even be knocked down to normal thread priority) if it exceeds its time quantum without blocking repeatedly" (<https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/scheduler/scheduler.html>).
- A boot argument (`-rt-allow_policy-enable`) can restrict the policy to threads in a work interval flagged `RT_ALLOWED`, demoting others (`thread_policy.c` lines 3384 to 3385 and 3454 to 3488). It is off unless set, and the local check below shows the policy is accepted on this machine.

### Core placement on this machine

`sysctl kern.sched` reports `edge`, so the Edge variant of the Clutch scheduler (`osfmk/kern/sched_clutch.c` under `CONFIG_SCHED_EDGE`) is the one running. In that code, threads at real time priority are always sent to their preferred cluster rather than load balanced ("For realtime threads, try and schedule them on the preferred pset always", `sched_clutch.c` lines 5413 to 5415); the default real time migration policy allows spill only among clusters of the same type and disallows it between heterogeneous clusters (lines 5853 and 5862); and the real time parallelism width is limited to the performance cores "since we do not spill/rebalance for RT threads" (lines 5982 to 5990). For non real time threads, only `BACKGROUND` and `MAINTENANCE` QoS are confined to efficiency cores because "the performance controller would never recommend execution on the P-cores" for them; every other QoS, including the default QoS the probe runs with today, may be placed on any core (lines 5992 to 6011). The older AMP scheduler file carries the same rules ("Never spill realtime threads", `osfmk/kern/sched_amp_common.c` lines 242 to 244; utility and background on E cores by default, lines 465 to 470). Apple's public guidance matches: "the system is more likely to run background tasks on lower performance cores to maximize battery life" (<https://developer.apple.com/documentation/apple-silicon/tuning-your-code-s-performance-for-apple-silicon>).

Which cluster is "preferred" for a given real time thread is decided by the performance controller, and the WWDC session says workgroups are "a new input into the performance controller" that "can also dynamically change the clock frequency of the CPUs" (WWDC20 10224 transcript). No primary source states that a real time thread outside any workgroup is guaranteed a performance core, so the stronger claim "P core" is not made here.

## Which clock to use

On Apple platforms libc++ implements `steady_clock::now()` as `clock_gettime(CLOCK_MONOTONIC_RAW)`, with the comment that only `CLOCK_UPTIME_RAW`, `CLOCK_MONOTONIC_RAW` or `mach_absolute_time` "are able to time functions in the nanosecond range" (<https://raw.githubusercontent.com/llvm/llvm-project/main/libcxx/src/chrono.cpp>, `__APPLE__` branch). Apple's Libc maps `CLOCK_MONOTONIC_RAW` to `mach_continuous_time()` and `CLOCK_UPTIME_RAW` to `mach_absolute_time()`, both scaled by `mach_timebase_info` (<https://raw.githubusercontent.com/apple-oss-distributions/Libc/main/gen/clock_gettime.c>, `clock_gettime_nsec_np`). The SDK man page confirms that `CLOCK_UPTIME_RAW` "is identical to the result of mach_absolute_time() after the appropriate mach_timebase conversion" and that `CLOCK_MONOTONIC_RAW` is the same clock except that it keeps counting during sleep (`usr/share/man/man3/clock_gettime.3`); `mach_continuous_time` is declared as "like mach_absolute_time, but advances during sleep" (`usr/include/mach/mach_time.h` lines 58 to 62).

On this machine `mach_timebase_info` is 125/3, so one tick is 41.67 ns, and `sysctl hw.tbfrequency` is 24000000 (output of the local check below). Consequences for the probe:

- The two clocks agree to the tick for any interval during which the machine does not sleep, so `steady_clock` is appropriate for durations and no change is needed.
- Durations are quantised to 41.67 ns, which is irrelevant at the microsecond scale the probe reports.
- `mach_absolute_time` units are what the kernel uses for deadlines (`sched_prim.c` line 863) and what the time constraint policy and workgroup intervals take (`thread_policy.h` lines 127 to 143; `usr/include/os/clock.h` lines 14 to 16 define `OS_CLOCK_MACH_ABSOLUTE_TIME` as the only clock id; the WWDC session warns "be sure not to assume that mach_absolute_time are nanoseconds ... use mach_timebase_info"). The recommended change therefore uses `mach_timebase_info` for the policy and `mach_wait_until` for pacing, and keeps `steady_clock` for the measured durations.

## Timer coalescing

Coalescing is enabled here (`sysctl kern.timer.coalescing_enabled` = 1). It is applied only when a timer is armed for a future deadline: `timer_call_slop` returns 0 unless `deadline > now` and the urgency is not system critical (`osfmk/kern/timer_call.c` lines 1927 to 1939). For a thread at priority `BASEPRI_RTQUEUES` or above, the real time shift and cap (`timer_coalesce_rt_shift`, `timer_coalesce_rt_abstime_max`) are used instead of the timeshare ones (lines 1868 to 1873). The values of the real time parameters are not exported by any `kern.timer_coalesce_*` sysctl on this machine (the listed tiers are `bg`, `kt`, `fp`, `ts` and `tier0` to `tier3`), so their numbers are not verified here. Apple's energy guide describes the user visible effect: a timer with tolerance "may fire anytime between its scheduled fire date and the scheduled fire date, plus the tolerance", and "The system may apply a small amount of tolerance even to timers that aren't given a specified amount" (<https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/Timers.html>).

The probe never arms a timer: its measured interval is the compute span between two `steady_clock` reads, so coalescing cannot change those numbers. What coalescing and scheduling latency do change is when the I/O thread wakes, and the probe does not model that. TN2169 measured `mach_wait_until` as the lowest overhead wait and says a wake "consistently missing your scheduled time by more than 500 microseconds" on an unloaded machine "should be considered an error" (<https://developer.apple.com/library/archive/technotes/tn2169/_index.html>). If ticket 07 wants a wake up jitter number, it can log `mach_absolute_time() - scheduled_wake` after each `mach_wait_until` as a separate metric.

## Recommended minimal probe change

All of this goes in `tools/pitchwing_live_probe.cpp` under `#ifdef __APPLE__`; the Linux and Windows builds are untouched. The policy values are derived from the case's block and rate:

- `period` = `block / rate` seconds, the host callback cadence (`AudioHardware.h` lines 945 to 946 for the buffer, `thread_policy.h` lines 127 to 130 for the field).
- `constraint` = `period`, because the probe's existing deadline test (`tools/pitchwing_live_probe.cpp` line 71) already defines "logically correct functioning" as finishing within the period (`thread_policy.h` lines 140 to 144).
- `computation` = `max(period / 2, 50 us)`. Anything below `constraint / 2` is raised to `constraint / 2` by the kernel anyway (`thread_policy.c` lines 415 to 419), so `period / 2` is the smallest value the kernel will honour as given, and it matches the 5 ms in 10 ms ratio of TN2169's example. The 50 us floor is `min_rt_quantum` (`sched_rt.c` lines 103 to 106); it only matters for block 1, whose period is below that floor at all three rates, and the local check shows those cases are rejected without it. `constraint` must then be `max(period, computation)` so block 1 stays valid.
- `preemptible` is ignored (`thread_policy.h` line 146), so `FALSE` as in TN2169.

```cpp
#ifdef __APPLE__
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/thread_policy.h>
#include <pthread.h>
#endif

namespace {
// Ticks of mach_absolute_time per nanosecond; 3/125 on Apple silicon.
double ticksPerNanosecond() {
#ifdef __APPLE__
    mach_timebase_info_data_t tb{};
    if (mach_timebase_info(&tb) == KERN_SUCCESS && tb.numer != 0)
        return static_cast<double>(tb.denom) / static_cast<double>(tb.numer);
#endif
    return 1.0;
}

// Moves the calling thread into the time constraint band for one case.
// Returns false (and leaves the thread unchanged) off macOS or on failure.
bool enterTimeConstraint(double rate, std::size_t block) {
#ifdef __APPLE__
    const double ticks = ticksPerNanosecond();
    const double periodNs = static_cast<double>(block) / rate * 1e9;
    const double computationNs = std::max(periodNs / 2, 50e3);      // min_rt_quantum
    const double constraintNs = std::max(periodNs, computationNs);  // >= computation
    thread_time_constraint_policy_data_t policy{};
    policy.period = static_cast<uint32_t>(periodNs * ticks);
    policy.computation = static_cast<uint32_t>(computationNs * ticks);
    policy.constraint = static_cast<uint32_t>(constraintNs * ticks);
    policy.preemptible = FALSE;
    const kern_return_t kr = thread_policy_set(
        pthread_mach_thread_np(pthread_self()), THREAD_TIME_CONSTRAINT_POLICY,
        reinterpret_cast<thread_policy_t>(&policy), THREAD_TIME_CONSTRAINT_POLICY_COUNT);
    return kr == KERN_SUCCESS;
#else
    (void)rate; (void)block;
    return false;
#endif
}

// Blocks until the given mach_absolute_time deadline; no-op off macOS.
void waitUntil(uint64_t deadlineTicks) {
#ifdef __APPLE__
    mach_wait_until(deadlineTicks);
#else
    (void)deadlineTicks;
#endif
}
} // namespace
```

In `timing()`, per case: call `enterTimeConstraint(rate, block)` right after constructing the engine and record the result in the JSON (for example `"time_constraint":true`); then pace the loop so the thread blocks once per callback:

```cpp
#ifdef __APPLE__
const double periodTicks = static_cast<double>(block) / rate * 1e9 * ticksPerNanosecond();
uint64_t nextWake = mach_absolute_time();
#endif
for (std::size_t offset = 0; offset < frames;) {
    // ... existing work and steady_clock measurement unchanged ...
#ifdef __APPLE__
    nextWake += static_cast<uint64_t>(periodTicks);
    waitUntil(nextWake);
#endif
    offset += n;
}
```

Why pacing is part of the minimum: the I/O thread "wakes up at regular intervals ... and the I/O thread sleeps" (Understanding Audio Workgroups), and a real time thread that never blocks for 1 s is demoted by the fail safe (`priority.c` lines 158 to 193 with the constants above), after which the remaining cases would silently run as timeshare again. The pacing makes `timing` take about 0.75 s of wall time per case (warm up plus measured audio at real time rate), roughly 18 s for the 24 cases; a `--no-pace` switch is a reasonable escape hatch but not required. The JSON should also record `"paced":true` so results from the two variants are never compared by accident.

Optional, outside the minimum: `mach_wait_until` returns after the deadline, so logging `mach_absolute_time() - nextWake` per callback gives the wake up lateness distribution that the HAL thread also experiences; and creating a work interval with `AudioWorkIntervalCreate` plus `os_workgroup_join` and `os_workgroup_interval_start`/`finish` around each callback would give the performance controller the duty cycle information it uses for clock frequency decisions (`AudioWorkInterval.h` lines 42 to 49; Apple's "Adding Asynchronous Real-Time Threads to Audio Workgroups" listing does exactly this, <https://developer.apple.com/documentation/audiotoolbox/adding-asynchronous-real-time-threads-to-audio-workgroups>). That requires linking AudioToolbox for the tool target, so it belongs in a separate ticket if the numbers from the minimal change are still implausible.

## Local verification of the policy values

A 60 line C check (`scratchpad/rtcheck/rtcheck.c`, not committed) called `thread_policy_set` on this machine with the values the recommendation derives, then read them back with `thread_policy_get`. Output, trimmed:

```
mach_timebase_info numer=125 denom=3 (1 tick = 41.666667 ns)
48k block 64:   period=1333.3us computation=666.7us  constraint=1333.3us -> kr=0 (successful); get returns the same values
44.1k block 128: period=2902.5us computation=1451.2us constraint=2902.5us -> kr=0 (successful)
96k block 32:   period=333.3us  computation=166.7us  constraint=333.3us  -> kr=0 (successful)
96k block 1:    period=10.4us   computation=5.2us    constraint=10.4us   -> kr=4 (invalid argument)
44.1k block 1:  period=22.7us   computation=11.3us   constraint=22.7us   -> kr=4 (invalid argument)
comp 49us / constraint 100us -> kr=4 (invalid argument)
comp 50us / constraint 100us -> kr=0 (successful)
comp 60ms / constraint 100ms -> kr=4 (invalid argument)
TN2169 5ms / 10ms            -> kr=0 (successful)
```

This confirms on the target kernel that an unentitled, unsigned command line process may enter the time constraint band; that the accepted `computation` range is exactly 50 us to 50 ms as `sched_rt.c` states; and that block 1 needs the 50 us floor in the recommendation.

## What plain steady_clock numbers mean without the change

They are the engine's compute cost per block on a default QoS timeshare thread: a lower bound on what a host callback will see when nothing else runs, with three caveats.

- Placement is unknown. A default QoS thread may be run on an efficiency core (`sched_clutch.c` lines 5992 to 6011 restrict only background and maintenance QoS), so a run can mix P core and E core samples, which widens p95 and max for reasons the DAW thread would not share. There is no primary source for the E to P throughput ratio of the M4 Pro, so the size of this effect is not estimated here.
- Preemption is unconstrained. A timeshare thread at priority 31 (`sched.h` line 163) can be preempted by any higher priority thread, including every real time thread on the system, whereas the probe thread with the policy sits at 97 and is preempted only by other real time threads with earlier deadlines (`sched_prim.c` lines 2518 to 2547). Outliers in `max_us` from the unmodified probe therefore say little about outliers a host would see.
- The counters measure compute time only. Neither variant measures wake up latency, workgroup driven clock frequency, or the `kAudioDevicePropertyIOCycleUsage` budget the HAL leaves to the client, so neither can declare a deadline "met" in the HAL's sense; the deadline count is a comparison against the full period only.

The existing WSL x86-64 numbers in `docs/results/2026-10-10-timing-step12.txt` are a different machine and OS and are not comparable to either macOS variant.

## Open questions

- The period, computation and constraint that the HAL uses for its own I/O thread and for the client render thread are not published in any Apple header or document I could reach; `kAudioDevicePropertyIOCycleUsage` only says the client gets a fraction of the cycle. The recommendation's `constraint = period` is the probe's own definition, not the HAL's.
- Which cluster the performance controller "prefers" for a real time thread outside any workgroup, and whether that changes once a work interval is active, is not stated in the Edge scheduler source or Apple's documentation. Ticket 07 should capture `thread_policy_get` and, if available, per core placement from Instruments rather than assume P cores.
- The real time timer coalescing parameters (`timer_coalesce_rt_shift`, `timer_coalesce_rt_ns_max`) are not exported by sysctl on this machine and their platform defaults were not found in the files read (`osfmk/arm/machine_routines_common.c` has no definition). They only matter for the optional wake up jitter metric.
- No Apple primary source covers how third party DAWs schedule VST3 processing (own real time worker threads versus the Core Audio client thread). The AU documentation shows all three cases are possible (real time in a workgroup, real time outside one, non real time), so results should be labelled with the thread configuration rather than with a host name.
- The libc++ implementation was read from upstream LLVM `main`, not from Apple's fork; the SDK header only declares `steady_clock` (`usr/include/c++/v1/__chrono/steady_clock.h` lines 26 to 35). The man page and Libc source are Apple's own and agree with the upstream comment, so the risk is low, but the exact dylib shipped with macOS 26.5.1 was not disassembled.

## Sources

Local files (SDK symlink `MacOSX.sdk` to `MacOSX26.5.sdk`):

- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/mach/thread_policy.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/mach/mach_time.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/mach/thread_act.h` (prototype of `thread_policy_set`, lines 316 to 329)
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/pthread/pthread.h` line 543 (`pthread_mach_thread_np`)
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/sys/qos.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/os/workgroup_object.h`, `os/workgroup_interval.h`, `os/clock.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/share/man/man3/clock_gettime.3`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/AudioToolbox.framework/Headers/AudioWorkInterval.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/AudioToolbox.framework/Headers/AudioUnitProperties.h`
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/CoreAudio.framework/Headers/AudioHardware.h`
- `sysctl` on the target: `kern.sched`, `hw.perflevel0.logicalcpu`, `hw.perflevel1.logicalcpu`, `hw.tbfrequency`, `kern.timer.coalescing_enabled`, `kern.timer_coalesce_*`

XNU, tag `xnu-12377.121.6` (<https://github.com/apple-oss-distributions/xnu>): `osfmk/kern/thread_policy.c`, `osfmk/kern/sched_rt.c`, `osfmk/kern/sched_prim.c`, `osfmk/kern/priority.c`, `osfmk/kern/sched_clutch.c`, `osfmk/kern/sched_amp_common.c`, `osfmk/kern/timer_call.c`, `osfmk/kern/work_interval.c`, `osfmk/kern/sched.h`, `osfmk/kern/thread.h`.

Apple documentation:

- Mach Scheduling and Thread Interfaces, Kernel Programming Guide (archived): <https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/scheduler/scheduler.html>
- TN2169, High Precision Timers in iOS / OS X (archived, last revised 2013): <https://developer.apple.com/library/archive/technotes/tn2169/_index.html>
- Understanding Audio Workgroups: <https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups>
- Adding Asynchronous Real-Time Threads to Audio Workgroups: <https://developer.apple.com/documentation/audiotoolbox/adding-asynchronous-real-time-threads-to-audio-workgroups>
- Workgroup Management: <https://developer.apple.com/documentation/audiotoolbox/workgroup-management>
- Tuning your code's performance for Apple silicon: <https://developer.apple.com/documentation/apple-silicon/tuning-your-code-s-performance-for-apple-silicon>
- Energy Efficiency Guide for Mac Apps, Timers (archived): <https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/Timers.html>
- WWDC20 session 10224, Meet Audio Workgroups: <https://developer.apple.com/videos/play/wwdc2020/10224/>

Other primary sources:

- libc++ `steady_clock` implementation: <https://raw.githubusercontent.com/llvm/llvm-project/main/libcxx/src/chrono.cpp>
- Apple Libc `clock_gettime`: <https://raw.githubusercontent.com/apple-oss-distributions/Libc/main/gen/clock_gettime.c>
