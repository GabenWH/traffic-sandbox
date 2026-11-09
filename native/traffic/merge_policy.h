// Shared phantom merge policy for fixed joins and parallel-lane changes.
// Included inside Engine; observations contain a common longitudinal ruler.
    static double arrival(double distance,double speed,double desired) {
        if(distance<=0) return 0;
        if(desired<=0.01) return inf;
        double a=desired>=speed?10:-24, t=(desired-speed)/a, d=(speed+desired)*t/2;
        if(distance<=d) return (std::sqrt(std::max(0.0,speed*speed+2*a*distance))-speed)/a;
        return t+(distance-d)/desired;
    }
    static bool gap(const Merge& m,double speed,double desired,double headway) {
        double begin=m.lateral_duration>0?0:arrival(std::max(0.0,m.distance-m.length),speed,desired);
        double finish=m.lateral_duration>0?m.lateral_duration:arrival(m.distance+m.length/2,speed,desired);
        if(finish==inf) return false;
        for(auto& r:m.reservations) if(arrival(std::max(0.0,m.distance+r.distance-m.length),speed,std::max(desired,m.cruise))<r.time+headway) return false;
        for(auto& v:m.vehicles) {
            auto& o=*v.car; double allowance=(m.length+o.s.length)/2+4;
            if(v.position+o.s.speed*begin>=allowance+headway*desired) {
                if(m.lateral_duration>0 && v.position+(o.s.speed-std::max(speed,desired))*finish<allowance+headway*desired)
                    return false;
                continue;
            }
            double cap=std::max({o.s.speed,o.cruise,speed,desired}),accel=std::min(finish,(cap-o.s.speed)/10);
            double travel=o.s.speed*accel+5*accel*accel+cap*(finish-accel);
            double moving_join=m.lateral_duration>0?std::min(speed,desired)*finish:0;
            if(v.position+travel-moving_join>-(allowance+headway*cap)) return false;
        }
        return true;
    }
    static Choice merge_choice(Car& c,const Merge& m,double cruise) {
        Choice choice;choice.desired=cruise;choice.entry=cruise;
        if(c.s.style==1) {
            choice.clear=gap(m,c.s.speed,cruise,2);
            if(!choice.clear) choice.reason="waiting for a generous merge gap";
            return choice;
        }
        double progress=clamp(1-m.distance/128,0,1),strength=progress*progress*(3-2*progress);
        double t=arrival(m.distance,c.s.speed,cruise),nearest=inf;
        Car* leader=nullptr;double position=0;
        for(auto& v:m.vehicles) {
            double p=v.position+v.car->s.speed*t;
            if(p>=0 && (!leader || p<nearest)) {nearest=p;leader=v.car;position=v.position;}
        }
        if(leader) {
            choice.phantom=leader->id;
            double g=position+m.distance-(m.length+leader->s.length)/2,wanted=6+0.8*c.s.speed;
            double response=0.8*(g-wanted)+1.2*(leader->s.speed-c.s.speed);
            choice.desired=std::min(cruise,cruise*(1-strength)+std::max(0.0,c.s.speed+response)*strength);
            if(leader->s.speed>0.1) {
                double opening=std::max(0.0,(18+0.8*c.s.speed-position)/leader->s.speed);
                if(opening>0) choice.desired=std::min(choice.desired,std::max(0.0,m.distance-m.length)/opening);
            }
        }
        choice.entry=std::max(choice.desired,std::min(cruise,6.0));
        choice.clear=gap(m,c.s.speed,choice.entry,0.8);
        if(!choice.phantom.empty() && choice.desired<cruise) choice.reason="matching speed behind phantom car";
        if(!choice.clear) choice.reason="yielding until the merge gap opens";
        return choice;
    }
