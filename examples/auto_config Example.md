template省略

config value範例: 參數都會集中管理而不是散落, 且能重用的都會重用

config/values.yaml
deploy-a
  images:
  version:
   - name: v604
     shadow: false
     replict: 1
   - name: v504
     shadow: true
     replict: 0

resource視情況而定, 如果prod和staging不同 通常都各自寫在prod staging(資源config, 比較沒那麼key),


config/phase/{fab}.yaml
global:
   phases:
     p1:
       dbname: MM01
       dbpassword: AAAA
       appDdbname: CC01
       appDdbpassword: ABC
     p2:
       dbname: MM02
       dbpassword: DDDD
       appDdbname: FCC02
       appDdbpassword: ABBB
     p3:
       dbname: MM03
       dbpassword: CCCC
       appDdbname: AMM03
       appDdbpassword: AAA
     p4:
       dbname: MM03
       dbpassword: CCCC
       appDdbname: AMM03
       appDdbpassword: AAA
     p7:
       dbname: MM03
       dbpassword: CCCC
       appDdbname: AMM03
       appDdbpassword: AAA

config/{workflow}/{fab}-{fz}/{env}.yaml or config/{workflow}/{fab}-{fz}/value.yaml
global:
   phases: ["p1", "p2", "p3"]
   spec_phase: ["p7"]
   all_phase: ["p1", "p2", "p3", "p4", "p7"]
   super_fab_phase: ["p4", "p7"]
   fab: "f14a'
   super_fab: "f14b"



經過渲染:

root/PROD/values.yaml
root/PROD/config/app_a/v504/application.yaml
root/PROD/config/app_a/v604/application.yaml
root/PROD/config/app_d/application-p1.yaml
root/PROD/config/app_d/application-p2.yaml
root/PROD/config/app_d/application-p3.yaml
root/PROD/config/app_eee/application-p1.yaml
root/PROD/config/app_eee/application-p2.yaml
root/PROD/config/app_eee/application-p3.yaml
root/PROD/config/app_eee/application-p4.yaml
root/PROD/config/app_eee/application-p7.yaml

values.yaml:
deploy-a:
  super-config: 
    - f14a-p1-config
    - f14a-p2-config
    - f14a-p3-config
    - f14b-p4-config
    - f14b-p7-config
  config: 
    - p1-config
    - p2-config
    - p3-config
    - p7-giga-config # 不一定會有或是可能每個廠區不同
  appE:
    p1:
      dbname: MM01
      dbpassword: AAAA
    p2:
      dbname: MM02
      dbpassword: DDDD
    p3:
      dbname: MM03
      dbpassword: CCCC
    p4:
      dbname: MM03
      dbpassword: CCCC
    p7:
      dbname: MM03
      dbpassword: CCCC
  appD:
    p1:
      dbname: CC01
      dbpassword: ABC
    p2:
      dbname: FCC02
      dbpassword: ABBB
    p3:
      dbname: AMM03
      dbpassword: AAA
  appC:
    p1:
      dbname: MM01
      dbpassword: AAAA
    p2:
      dbname: MM02
      dbpassword: DDDD
    p3:
      dbname: MM03
      dbpassword: CCCC
  appB:
    p1:
      dbname: MMP1
      dbpassword: $(p1_password)
    p2:
      dbname: MMP2
      dbpassword: $(p2_password)
    p3:
      dbname: MMP3
      dbpassword: $(p3_password)

  appA:
    p1:
      - name: v604
        shadow: false
        replict: 1
        resource:
          cpu: 5
          gpu: 5
          hpa:
            dataa: 1
            datab: 1
          res:
            dataa: 2
            datab: 2
      - name: v512
        shadow: true
        replict: 0
        resource:
          cpu: 5
          gpu: 5
          res:
            dataa: 2
            datab: 2
    p2:
      - name: v604
        shadow: false
        replict: 1
        resource:
          cpu: 5
          gpu: 5
          hpa:
            dataa: 1
            datab: 1
          res:
            dataa: 2
            datab: 2
      - name: v512
        shadow: true
        replict: 0
        resource:
          cpu: 5
          gpu: 5
          res:
            dataa: 2
            datab: 2
    p3:
      - name: v604
        shadow: false
        replict: 1
        resource:
          cpu: 5
          gpu: 5
          hpa:
            dataa: 1
            datab: 1
          res:
            dataa: 2
            datab: 2
      - name: v512
        shadow: true
        replict: 0
        resource:
          cpu: 5
          gpu: 5
          res:
            dataa: 2
            datab: 2