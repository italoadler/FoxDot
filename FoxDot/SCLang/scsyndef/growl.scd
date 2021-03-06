SynthDef.new( \growl,{|vib=0, vibVar=0.04, echo=0, depthVar=0.1, vibDelay=0, slide=0, delay=0, sus=1, hpf=0, pan=0, scrub=0, verb=0.25, amp=1, freq=0, buf=0, echoOn=0, room=1, rate=0, depth=0.02, grain=0, lpf=20000, slidefrom=1|var osc,env;
sus=(sus * 1.5);
freq=Vibrato.kr(Line.ar((freq * slidefrom), (freq * (1 + slide)), sus), delay: vibDelay, depthVariation: depthVar, rate: vib, rateVariation: vibVar, depth: depth);
osc=LPF.ar(HPF.ar((SinOsc.ar((Vibrato.kr(Line.ar((freq * slidefrom), (freq * (1 + slide)), sus), delay: vibDelay, depthVariation: depthVar, rate: vib, rateVariation: vibVar, depth: depth) + SinOsc.kr(0.5, mul: 2, add: 1)), mul: amp) * Saw.ar((((sus * 1.5) / 1.5) * 32))), hpf), (lpf + 1));
env=EnvGen.ar(Env(releaseTime: sus, level: amp, levels: [0, amp, 0], times: [(sus / 2), (sus / 2)]).delay(delay), doneAction: 2);
Out.ar(0, Pan2.ar(FreeVerb.ar(osc * env, verb, room), pan))}).add;