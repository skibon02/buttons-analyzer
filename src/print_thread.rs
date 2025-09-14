use std::fmt::Debug;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use log::info;
use ringbuf::consumer::Consumer;
use crate::{Shared, TICKS_PER_S};

pub fn spawn(shared: Arc<Mutex<Shared>>) {
    thread::spawn(move || {
        loop {
            thread::sleep(Duration::from_secs(1));

            let guard = shared.lock().unwrap();
            let (s1, s2) = guard.last_presses.as_slices();
            let mut deltas =  s1.to_vec();
            deltas.extend_from_slice(s2);
            drop(guard);

            let deltas = deltas.iter().map(|(d, is_z)| (*d * 1000 / TICKS_PER_S.load(std::sync::atomic::Ordering::Relaxed), *is_z)).collect::<Vec<_>>();
            if deltas.len() < 2 {
                info!("C'mon, smash these buttons!");
                continue;
            }

            let mut min = u64::MAX;
            let mut max = 0;
            let mut sum = 0;
            for (d, is_z) in &deltas {
                let d = *d;
                if d > max {
                    max = d;
                }
                if d < min {
                    min = d;
                }
                sum += d;
            }

            let total_stats = calc_stats(&deltas, sum);
            info!("");
            info!("");
            info!("");
            info!("Total: {:?}", total_stats);
            if deltas.len() >= 4 {
                let win_4_stats = calc_stats_windows(&deltas, 4, 1);
                let best_4_bpm = win_4_stats.iter().max_by(|a, b| a.bpm.partial_cmp(&b.bpm).unwrap());
                if let Some(best_4_bpm) = best_4_bpm {
                    let best_4_ur = win_4_stats.iter().min_by(|a, b| a.ur.partial_cmp(&b.ur).unwrap()).unwrap();

                    info!("Best 4 BPM: {:?}", best_4_bpm);
                    info!("Best 4 UR: {:?}", best_4_ur);
                }
            }

            if deltas.len() >= 20 {
                let win_20_stats = calc_stats_windows(&deltas, 20, 1);
                let best_20_bpm = win_20_stats.iter().max_by(|a, b| a.bpm.partial_cmp(&b.bpm).unwrap());
                if let Some(best_20_bpm) = best_20_bpm {
                    let best_20_ur = win_20_stats.iter().min_by(|a, b| a.ur.partial_cmp(&b.ur).unwrap()).unwrap();

                    info!("Best 20 BPM: {:?}", best_20_bpm);
                    info!("Best 20 UR: {:?}", best_20_ur);
                }
            }

            if deltas.len() >= 500 {
                let win_500_stats = calc_stats_windows(&deltas, 500, 10);
                let best_500_bpm = win_500_stats.iter().max_by(|a, b| a.bpm.partial_cmp(&b.bpm).unwrap());
                if let Some(best_500_bpm) = best_500_bpm {
                    let best_500_ur = win_500_stats.iter().min_by(|a, b| a.ur.partial_cmp(&b.ur).unwrap()).unwrap();

                    info!("Best 500 BPM: {:?}", best_500_bpm);
                    info!("Best 500 UR: {:?}", best_500_ur);
                }
            }

            if deltas.len() >= 2000 {
                let win_2000_stats = calc_stats_windows(&deltas, 2000, 50);
                let best_2000_bpm = win_2000_stats.iter().max_by(|a, b| a.bpm.partial_cmp(&b.bpm).unwrap());
                if let Some(best_2000_bpm) = best_2000_bpm {
                    let best_2000_ur = win_2000_stats.iter().min_by(|a, b| a.ur.partial_cmp(&b.ur).unwrap()).unwrap();

                    info!("Best 2000 BPM: {:?}", best_2000_bpm);
                    info!("Best 2000 UR: {:?}", best_2000_ur);
                }
            }
            info!("");
            info!("");
            if deltas.len() >= 20 {
                let recent_stats = calc_stats(&deltas[deltas.len()-20..], deltas[deltas.len()-20..].iter().map(|(d, _)| *d).sum());
                info!("Cur: {:?}", recent_stats);
            }
        }
    });
}

pub struct Stats {
    pub ur: f64,
    pub bpm: f64,
    pub zx_ratio: f64,
}

impl Debug for Stats {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "(BPM: {:.0}, UR: {:.0}, ZX: {:.0}%)", self.bpm, self.ur, self.zx_ratio * 100.0)
    }
}

fn calc_stats_windows(deltas: &[(u64, bool)], window: u64, step: u64) -> Vec<Stats> {
    let mut stats = Vec::with_capacity((deltas.len() as u64 - window) as usize / step as usize);
    let mut sum = None;
    for i in 0..(deltas.len() as u64 - window) / step {
        let start = (i * step) as usize;
        let end = start + window as usize;

        if sum.is_none() {
            sum = Some(deltas[start..end].iter().map(|v| v.0).sum::<u64>());
        } else {
            let mut new_sum = sum.unwrap();
            for i in 0..step {
                new_sum = new_sum - deltas[start - 1 - i as usize].0 + deltas[end - 1 - i as usize].0;
            }
            sum = Some(new_sum);
        }

        stats.push(calc_stats(&deltas[start..end], sum.unwrap()));
    }

    stats
}

fn calc_stats(deltas: &[(u64, bool)], sum: u64) -> Stats {
    let window = deltas.len() as u64;
    let avg = sum / window;

    let mut sq_sum = 0;
    let sum_z = deltas.iter().filter(|(_, is_z)| *is_z).map(|(d, _)| *d).sum::<u64>();
    let sum_x = sum - sum_z;
    let zx_coef = sum_x as f64 / sum as f64 - 0.5;

    for &d in deltas {
        sq_sum += d.0.abs_diff(avg).pow(2);
    }

    let std_dev = (sq_sum as f64 / (window as f64 - 1.0)).sqrt();
    let ur = std_dev * 10.0;

    let bpm = if avg > 0 {
        60000.0 / avg as f64 / 4.0
    } else {
        0.0
    };

    Stats { ur, bpm, zx_ratio: zx_coef }
}